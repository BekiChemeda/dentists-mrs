from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import TimestampedModel, UUIDModel
from apps.core.concurrency import Versioned

username_validator = RegexValidator(
    r"^[a-z0-9][a-z0-9._-]{2,49}$",
    "Use 3–50 lowercase letters, digits, dots, hyphens or underscores, starting with a letter or digit.",
)


class Permission(UUIDModel):
    """An action the backend checks, e.g. `patients.view`. Seeded from catalog.py."""

    code = models.CharField(max_length=100, unique=True)
    module = models.CharField(max_length=50)
    description = models.CharField(max_length=255)

    class Meta:
        db_table = "accounts_permission"
        ordering = ["module", "code"]

    def __str__(self) -> str:
        return self.code


class Role(Versioned, TimestampedModel):
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=False, help_text="Shipped role; cannot be deleted.")
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        db_table = "accounts_role"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username: str) -> User:
        return self.get(username__iexact=username)

    def create_user(self, username: str, password: str | None = None, **extra) -> User:
        user = self.model(username=username.strip().lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class Department(Versioned, TimestampedModel):
    """
    A unit of the clinic (OPD 1, laboratory, labour ward...). Staff are assigned to one; departments
    marked `receives_triage` are the places a nurse can send a patient after triage.
    """

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=100, unique=True)
    receives_triage = models.BooleanField(default=False, help_text="Offered as a 'Triage to' destination.")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "accounts_department"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Room(Versioned, TimestampedModel):
    """A consultation or treatment room. A doctor picks the room they work in today; when they call a patient,
    the waiting list shows which room to go to."""

    name = models.CharField(max_length=60, unique=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="rooms")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "accounts_room"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class User(Versioned, AbstractBaseUser, TimestampedModel):
    """
    One account per staff member. Accounts are deactivated, never deleted, because audit
    events and clinical records reference them.
    """

    username = models.CharField(max_length=50, unique=True, validators=[username_validator])
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)

    class EmailAlerts(models.TextChoices):
        OFF = "off", "None"
        IMPORTANT = "important", "Important only"
        ALL = "all", "Everything"

    # Which notifications are also sent by email (when the clinic has email set up).
    # Security notices about one's own account are always emailed.
    email_alerts = models.CharField(max_length=10, choices=EmailAlerts.choices, default=EmailAlerts.IMPORTANT)
    phone = models.CharField(max_length=20, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    # Professional licence/registration number. Printed on prescriptions, referrals and certificates;
    # EFDA Directive 1121/2025 Art. 22 requires it on controlled-medicine prescriptions.
    registration_number = models.CharField(max_length=50, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="staff")
    start_date = models.DateField(null=True, blank=True)
    # The room this person works in now; doctors set it themselves. Shown when they call a patient.
    room = models.ForeignKey("Room", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    # Two-step sign-in (apps/accounts/mfa.py). The secret is stored encrypted, never in clear text.
    mfa_secret_encrypted = models.TextField(blank=True)
    mfa_enabled_at = models.DateTimeField(null=True, blank=True)
    mfa_last_step = models.BigIntegerField(null=True, blank=True)

    roles = models.ManyToManyField(Role, related_name="users", blank=True)
    created_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.username})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def is_locked(self, now=None) -> bool:
        return bool(self.locked_until and self.locked_until > (now or timezone.now()))

    @property
    def permission_codes(self) -> frozenset[str]:
        """Cached per instance (i.e. per request); roles changes take effect on the next request."""
        cached = getattr(self, "_permission_codes", None)
        if cached is None:
            if not self.is_active:
                cached = frozenset()
            else:
                from apps.core.modules import disabled_permissions

                # Permissions of switched-off modules are taken away from every role while they are off.
                cached = frozenset(
                    Permission.objects.filter(roles__users=self).values_list("code", flat=True).distinct()
                ) - disabled_permissions()
            self._permission_codes = cached
        return cached

    @property
    def role_permission_codes(self) -> frozenset[str]:
        """What the person's roles grant, ignoring switched-off modules (used only to explain refusals)."""
        if not self.is_active:
            return frozenset()
        return frozenset(Permission.objects.filter(roles__users=self).values_list("code", flat=True).distinct())

    def has_permissions(self, codes: Iterable[str]) -> bool:
        return set(codes).issubset(self.permission_codes)

    def has_any_permission(self, codes: Iterable[str]) -> bool:
        return bool(set(codes) & self.permission_codes)

    @property
    def mfa_enabled(self) -> bool:
        return bool(self.mfa_enabled_at and self.mfa_secret_encrypted)

    def clear_permission_cache(self) -> None:
        self.__dict__.pop("_permission_codes", None)


class RecoveryCode(models.Model):
    """Single-use code for signing in when the authenticator phone is lost. Stored hashed."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_recovery_code"


class UserSession(UUIDModel):
    """Maps Django sessions to users so sessions can be listed and revoked."""

    class EndReason(models.TextChoices):
        LOGOUT = "logout", "Signed out"
        REVOKED = "revoked", "Ended by administrator"
        DEACTIVATED = "deactivated", "Account deactivated"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sessions")
    session_key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, choices=EndReason.choices, blank=True)
    # The activated phone an app sign-in came from (apps/devices); empty for web sessions.
    device = models.ForeignKey("devices.MobileDevice", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="sessions")

    class Meta:
        db_table = "accounts_user_session"
        indexes = [models.Index(fields=["user", "ended_at"], name="usersession_active_idx")]

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def absolute_expiry(self):
        return self.created_at + timedelta(hours=settings.SESSION_ABSOLUTE_TIMEOUT_HOURS)


class LoginAttempt(UUIDModel):
    """Every login attempt, successful or not. Used for lockout review and security reports."""

    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)
    username_entered = models.CharField(max_length=150)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    succeeded = models.BooleanField()
    failure_reason = models.CharField(max_length=30, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "accounts_login_attempt"
        ordering = ["-attempted_at"]
        indexes = [models.Index(fields=["ip_address", "-attempted_at"], name="loginattempt_ip_idx")]
