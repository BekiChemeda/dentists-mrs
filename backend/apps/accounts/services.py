"""
Business rules for accounts, roles and sessions.

Every state change runs in a transaction together with its audit event. Views call these
functions; they never write account tables directly.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError as DjangoValidationError

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core import policy
from apps.core.context import ActorContext
from apps.core.exceptions import AccountLocked, BusinessValidationError, ConflictError, DomainError

from apps.core.exceptions import PermissionDeniedError

from .catalog import ADMIN_PERMISSIONS, role_is_privileged
from .models import Department, LoginAttempt, Permission, Role, User, UserSession

logger = logging.getLogger(__name__)


class InvalidCredentials(DomainError):
    status_code = 400
    code = "invalid_credentials"


# A valid Argon2 hash used to equalise response time for unknown usernames.
_DUMMY_PASSWORD_HASH = None


def _dummy_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = make_password(secrets.token_urlsafe(16))
    return _DUMMY_PASSWORD_HASH


# ---------------------------------------------------------------------------
# Login, logout, sessions
# ---------------------------------------------------------------------------
def verify_credentials(ctx: ActorContext, username: str, password: str) -> User:
    """
    Check a username/password with lockout. Returns the user on success.

    Failures are recorded (and committed) before the error is raised. The same generic
    message is used for unknown users, wrong passwords and inactive accounts, so the
    endpoint does not reveal which usernames exist.
    """
    username = (username or "").strip().lower()
    now = timezone.now()
    failure: tuple[str, User | None] | None = None
    locked_until = None

    with transaction.atomic():
        user = User.objects.select_for_update().filter(username=username).first()
        if user is None:
            from django.contrib.auth.hashers import check_password

            check_password(password, _dummy_hash())
            failure = ("unknown_user", None)
        elif user.is_locked(now):
            failure = ("locked", user)
            locked_until = user.locked_until
        elif not user.check_password(password):
            locked_until = _register_failure(ctx, user, now, "bad_password")
            failure = ("bad_password", user)
        elif not user.is_active:
            failure = ("inactive", user)
        elif user.mfa_enabled:
            # Password right; the sign-in is completed by complete_mfa_login(). Failure counters are
            # left as they are, so guessing codes still leads to a lockout.
            record_event(ctx, action="auth.password_ok", object_type="user", object_id=user.pk, actor=user)
            return user
        else:
            _finish_login(ctx, username, user, now)
            return user

        reason, attempted_user = failure
        _log_attempt(ctx, username, attempted_user, succeeded=False, reason=reason)
        record_event(ctx, action="auth.login", object_type="user",
                     object_id=attempted_user.pk if attempted_user else "",
                     outcome="failure", actor=attempted_user,
                     details={"reason": reason, "username_entered": username[:150]})

    # Transaction committed: the failure is recorded even though we now raise.
    if locked_until is not None:
        minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
        raise AccountLocked(
            f"Too many failed sign-in attempts. Try again in about {minutes} minute(s) "
            "or ask an administrator to unlock the account."
        )
    raise InvalidCredentials("Incorrect username or password.")


def _finish_login(ctx, username, user, now, **details) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login = now
    user.save(update_fields=["failed_login_count", "locked_until", "last_login", "updated_at"])
    _log_attempt(ctx, username, user, succeeded=True)
    record_event(ctx, action="auth.login", object_type="user", object_id=user.pk, actor=user, details=details)


def _security_email(user, title: str, body: str) -> None:
    """Email the person about a change to their own account (if the clinic has email set up)."""
    from apps.notifications.email import security_notice

    try:
        with transaction.atomic():
            security_notice(user, title, body)
    except Exception:  # noqa: BLE001 - never block the security action itself
        logger.warning("Could not queue security email", exc_info=True)


def _register_failure(ctx, user, now, reason: str):
    """Count a failed attempt towards the lockout. Returns the lock end time if this locked the account."""
    user.failed_login_count += 1
    locked_until = None
    if user.failed_login_count >= policy.login_max_failures():
        lockout_minutes = policy.login_lockout_minutes()
        user.locked_until = locked_until = now + timedelta(minutes=lockout_minutes)
        user.failed_login_count = 0
        record_event(ctx, action="auth.account_locked", object_type="user", object_id=user.pk,
                     outcome="failure", actor=user, details={"lockout_minutes": lockout_minutes, "reason": reason})
        _security_email(user, "Your account was locked",
                        f"Your Clinic MRS account was locked for {lockout_minutes} minutes after repeated failed sign-ins.")
    user.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
    return locked_until


def _log_attempt(ctx, username, user, *, succeeded, reason=""):
    LoginAttempt.objects.create(
        username_entered=username[:150],
        user=user,
        succeeded=succeeded,
        failure_reason=reason,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
    )


def start_session(ctx: ActorContext, user: User, session_key: str) -> UserSession:
    return UserSession.objects.create(
        user=user, session_key=session_key, ip_address=ctx.ip_address, user_agent=ctx.user_agent
    )


@transaction.atomic
def end_session(ctx: ActorContext, session_key: str | None, reason: str) -> None:
    if not session_key:
        return
    updated = UserSession.objects.filter(session_key=session_key, ended_at__isnull=True).update(
        ended_at=timezone.now(), end_reason=reason
    )
    if updated and reason == UserSession.EndReason.LOGOUT:
        record_event(ctx, action="auth.logout", object_type="user", object_id=ctx.user.pk if ctx.user else "")


def _revoke_all_sessions(user: User, reason: str, *, keep_session_key: str | None = None) -> int:
    active = UserSession.objects.filter(user=user, ended_at__isnull=True)
    if keep_session_key:
        active = active.exclude(session_key=keep_session_key)
    keys = list(active.values_list("session_key", flat=True))
    Session.objects.filter(session_key__in=keys).delete()
    active.update(ended_at=timezone.now(), end_reason=reason)
    return len(keys)


@transaction.atomic
def revoke_sessions(ctx: ActorContext, user: User) -> int:
    count = _revoke_all_sessions(user, UserSession.EndReason.REVOKED)
    record_event(ctx, action="user.sessions_revoked", object_type="user", object_id=user.pk,
                 details={"sessions_ended": count})
    return count


def touch_session(session: UserSession) -> None:
    now = timezone.now()
    if (now - session.last_seen_at).total_seconds() >= 60:
        UserSession.objects.filter(pk=session.pk).update(last_seen_at=now)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
_TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_temporary_password(length: int = 12) -> str:
    while True:
        candidate = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(length))
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            return candidate


def _validate_new_password(password: str, user: User) -> None:
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise BusinessValidationError("Password does not meet the requirements.",
                                      fields={"new_password": list(exc.messages)}) from exc


def change_own_password(ctx: ActorContext, user: User, current_password: str, new_password: str,
                        current_session_key: str | None) -> None:
    if not user.check_password(current_password):
        # Recorded in its own transaction so the failure survives the error response.
        with transaction.atomic():
            record_event(ctx, action="auth.password_change", object_type="user", object_id=user.pk,
                         outcome="failure", details={"reason": "wrong_current_password"})
        raise BusinessValidationError("Current password is incorrect.",
                                      fields={"current_password": ["Current password is incorrect."]})
    if current_password == new_password:
        raise BusinessValidationError("Choose a password different from the current one.",
                                      fields={"new_password": ["Must differ from the current password."]})
    _validate_new_password(new_password, user)
    with transaction.atomic():
        _apply_new_password(ctx, user, new_password, current_session_key)


def _apply_new_password(ctx: ActorContext, user: User, new_password: str, current_session_key: str | None) -> None:
    user.set_password(new_password)
    user.must_change_password = False
    user.password_changed_at = timezone.now()
    user.save(update_fields=["password", "must_change_password", "password_changed_at", "updated_at"])
    ended = _revoke_all_sessions(user, UserSession.EndReason.PASSWORD_CHANGED,
                                 keep_session_key=current_session_key)
    record_event(ctx, action="auth.password_change", object_type="user", object_id=user.pk,
                 details={"other_sessions_ended": ended})
    _security_email(user, "Your password was changed", "The password of your Clinic MRS account was changed.")


def rekey_session(old_key: str | None, new_key: str | None) -> None:
    if old_key and new_key and old_key != new_key:
        UserSession.objects.filter(session_key=old_key).update(session_key=new_key)


@transaction.atomic
def admin_reset_password(ctx: ActorContext, user: User) -> str:
    """Issue a one-time temporary password. The user must change it at next sign-in."""
    _forbid_self(ctx, user, "reset your own password here; use Change password instead")
    _check_staff_scope(ctx, target=user)
    temporary = generate_temporary_password()
    user.set_password(temporary)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    user.save(update_fields=["password", "must_change_password", "failed_login_count", "locked_until",
                             "updated_at"])
    ended = _revoke_all_sessions(user, UserSession.EndReason.REVOKED)
    record_event(ctx, action="user.password_reset", object_type="user", object_id=user.pk,
                 details={"sessions_ended": ended})
    # The temporary password itself is never emailed: the administrator hands it over in person.
    _security_email(user, "Your password was reset",
                    "An administrator reset your Clinic MRS password. You will get a temporary password from them in person.")
    return temporary


@transaction.atomic
def unlock_user(ctx: ActorContext, user: User) -> None:
    _check_staff_scope(ctx, target=user)
    user.failed_login_count = 0
    user.locked_until = None
    user.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
    record_event(ctx, action="user.unlock", object_type="user", object_id=user.pk)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _forbid_self(ctx: ActorContext, user: User, what: str) -> None:
    if ctx.user is not None and ctx.user.pk == user.pk:
        raise ConflictError(f"You cannot {what}.")


def _roles_from_ids(role_ids) -> list[Role]:
    role_ids = list(dict.fromkeys(role_ids or []))
    roles = list(Role.objects.filter(pk__in=role_ids))
    if len(roles) != len(role_ids):
        raise BusinessValidationError("One or more roles do not exist.", fields={"role_ids": ["Unknown role."]})
    return roles


def is_privileged_role(role: Role) -> bool:
    return role_is_privileged(role.code, role.permissions.values_list("code", flat=True))


def _staff_scope_only(ctx: ActorContext) -> bool:
    """True when the actor manages accounts through staff.manage, without full users.manage."""
    return ctx.user is not None and not ctx.user.has_permissions(["users.manage"])


def _check_staff_scope(ctx: ActorContext, *, target: User | None = None, roles=None) -> None:
    """
    Holders of staff.manage (clinic administrators) work only with ordinary clinic accounts: they cannot
    assign a privileged role, or change an account that already has one.
    """
    if not _staff_scope_only(ctx):
        return
    # The exception handler records the refusal as access.denied, after the transaction has ended.
    if roles is not None and any(is_privileged_role(r) for r in roles):
        raise PermissionDeniedError("Only a system administrator can give a role with administrative rights.")
    if target is not None and any(is_privileged_role(r) for r in target.roles.all()):
        raise PermissionDeniedError("This account has administrative rights; only a system administrator can change it.")


def _department(department_id) -> Department | None:
    if not department_id:
        return None
    dept = Department.objects.filter(pk=department_id).first()
    if dept is None:
        raise BusinessValidationError("Unknown department.", fields={"department_id": ["Unknown department."]})
    return dept


def _ensure_admin_remains() -> None:
    """Refuse any change that leaves nobody able to manage users and roles."""
    qs = User.objects.filter(is_active=True)
    for code in ADMIN_PERMISSIONS:
        qs = qs.filter(roles__permissions__code=code)
    if not qs.exists():
        raise ConflictError(
            "This change would leave no active account able to manage users and roles."
        )


@transaction.atomic
def create_user(ctx: ActorContext, *, username: str, first_name: str, last_name: str, email: str = "",
                phone: str = "", job_title: str = "", registration_number: str = "", role_ids=(),
                department_id=None, start_date=None) -> tuple[User, str]:
    username = username.strip().lower()
    roles = _roles_from_ids(role_ids)
    _check_staff_scope(ctx, roles=roles)
    if User.objects.filter(username__iexact=username).exists():
        raise ConflictError("That username is already taken.", fields={"username": ["Already taken."]})
    user = User(username=username, first_name=first_name.strip(), last_name=last_name.strip(),
                email=email.strip(), phone=phone.strip(), job_title=job_title.strip(),
                registration_number=registration_number.strip(), department=_department(department_id),
                start_date=start_date, must_change_password=True, created_by=ctx.user)
    temporary = generate_temporary_password()
    user.set_password(temporary)
    user.full_clean(exclude=["password"])
    user.save()
    user.roles.set(roles)
    record_event(ctx, action="user.create", object_type="user", object_id=user.pk,
                 details={"username": username, "roles": sorted(r.code for r in roles),
                          **({"department": user.department.code} if user.department else {})})
    return user, temporary


_EDITABLE_FIELDS = ("first_name", "last_name", "email", "phone", "job_title", "registration_number")


@transaction.atomic
def update_user(ctx: ActorContext, user: User, *, role_ids=None, **fields) -> User:
    user = User.objects.select_for_update().get(pk=user.pk)
    _check_staff_scope(ctx, target=user)
    changes: dict[str, dict] = {}
    if "department_id" in fields:
        dept = _department(fields.pop("department_id"))
        if dept != user.department:
            changes["department"] = {"from": user.department.code if user.department else "",
                                     "to": dept.code if dept else ""}
            user.department = dept
    if "start_date" in fields:
        start = fields.pop("start_date")
        if start != user.start_date:
            changes["start_date"] = {"from": str(user.start_date or ""), "to": str(start or "")}
            user.start_date = start
    for name in _EDITABLE_FIELDS:
        if name in fields:
            new = (fields[name] or "").strip()
            old = getattr(user, name)
            if new != old:
                changes[name] = {"from": old, "to": new}
                setattr(user, name, new)
    if changes:
        user.full_clean(exclude=["password"])
        user.save()

    if role_ids is not None:
        _forbid_self(ctx, user, "change your own roles")
        new_roles = _roles_from_ids(role_ids)
        _check_staff_scope(ctx, roles=new_roles)
        old_codes = set(user.roles.values_list("code", flat=True))
        new_codes = {r.code for r in new_roles}
        if old_codes != new_codes:
            user.roles.set(new_roles)
            changes["roles"] = {"added": sorted(new_codes - old_codes), "removed": sorted(old_codes - new_codes)}
            _ensure_admin_remains()

    if changes:
        record_event(ctx, action="user.update", object_type="user", object_id=user.pk, details=changes)
    user.clear_permission_cache()
    return user


@transaction.atomic
def set_user_active(ctx: ActorContext, user: User, active: bool) -> User:
    user = User.objects.select_for_update().get(pk=user.pk)
    _check_staff_scope(ctx, target=user)
    if user.is_active == active:
        return user
    if not active:
        _forbid_self(ctx, user, "deactivate your own account")
    user.is_active = active
    user.save(update_fields=["is_active", "updated_at"])
    ended = 0
    if not active:
        ended = _revoke_all_sessions(user, UserSession.EndReason.DEACTIVATED)
        _ensure_admin_remains()
    record_event(ctx, action="user.activate" if active else "user.deactivate", object_type="user",
                 object_id=user.pk, details={"sessions_ended": ended} if not active else {})
    return user


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def _permissions_from_codes(codes) -> list[Permission]:
    codes = list(dict.fromkeys(codes or []))
    perms = list(Permission.objects.filter(code__in=codes))
    if len(perms) != len(codes):
        unknown = sorted(set(codes) - {p.code for p in perms})
        raise BusinessValidationError("Unknown permission codes.", fields={"permission_codes": unknown})
    return perms


@transaction.atomic
def create_role(ctx: ActorContext, *, code: str, name: str, description: str = "",
                permission_codes=()) -> Role:
    if Role.objects.filter(code=code).exists() or Role.objects.filter(name__iexact=name).exists():
        raise ConflictError("A role with that code or name already exists.")
    role = Role(code=code, name=name.strip(), description=description.strip(), is_system=False)
    role.full_clean()
    role.save()
    perms = _permissions_from_codes(permission_codes)
    role.permissions.set(perms)
    record_event(ctx, action="role.create", object_type="role", object_id=role.pk,
                 details={"code": code, "permissions": sorted(p.code for p in perms)})
    return role


@transaction.atomic
def update_role(ctx: ActorContext, role: Role, *, name=None, description=None, permission_codes=None) -> Role:
    role = Role.objects.select_for_update().get(pk=role.pk)
    changes: dict[str, dict] = {}
    if name is not None and name.strip() != role.name:
        if Role.objects.filter(name__iexact=name.strip()).exclude(pk=role.pk).exists():
            raise ConflictError("A role with that name already exists.")
        changes["name"] = {"from": role.name, "to": name.strip()}
        role.name = name.strip()
    if description is not None and description.strip() != role.description:
        changes["description"] = {"from": role.description, "to": description.strip()}
        role.description = description.strip()
    if changes:
        role.save()
    if permission_codes is not None:
        perms = _permissions_from_codes(permission_codes)
        old = set(role.permissions.values_list("code", flat=True))
        new = {p.code for p in perms}
        if old != new:
            role.permissions.set(perms)
            changes["permissions"] = {"added": sorted(new - old), "removed": sorted(old - new)}
            _ensure_admin_remains()
    if changes:
        record_event(ctx, action="role.update", object_type="role", object_id=role.pk, details=changes)
    return role


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
@transaction.atomic
def save_department(ctx: ActorContext, dept: Department | None, data: dict) -> Department:
    creating = dept is None
    dept = dept or Department()
    changes = {}
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        if getattr(dept, key) != value:
            changes[key] = {"from": getattr(dept, key), "to": value} if not creating else value
            setattr(dept, key, value)
    if not creating and "code" in changes:
        raise BusinessValidationError("A department code cannot change; it is stored on triage records.",
                                      fields={"code": ["Cannot be changed."]})
    if not changes:
        return dept
    dept.full_clean()
    dept.save()
    record_event(ctx, action="department.create" if creating else "department.update", object_type="department",
                 object_id=dept.pk, details={k: v if not isinstance(v, dict) else
                                              {kk: str(vv) for kk, vv in v.items()} for k, v in changes.items()})
    return dept


# ---------------------------------------------------------------------------
# Two-step sign-in
# ---------------------------------------------------------------------------
from django.core import signing  # noqa: E402

from . import mfa as mfa_lib  # noqa: E402
from .models import RecoveryCode  # noqa: E402

_MFA_SALT = "mrs.accounts.mfa-login"
MFA_TOKEN_MAX_AGE = 300


def mfa_required_for(user: User) -> bool:
    """Whether the security policy requires this user to use two-step sign-in."""
    from apps.core.models import SystemSettings

    rule = SystemSettings.get().mfa_required_for
    if rule == "all":
        return True
    if rule == "admins":
        return any(is_privileged_role(r) for r in user.roles.all())
    return False


def mfa_setup_required(user: User) -> bool:
    return not user.mfa_enabled and mfa_required_for(user)


def mfa_login_token(user: User) -> str:
    # Includes the end of the password hash, so a password change invalidates outstanding tokens.
    return signing.dumps({"u": str(user.pk), "p": user.password[-16:]}, salt=_MFA_SALT)


def complete_mfa_login(ctx: ActorContext, token: str, code: str) -> User:
    try:
        data = signing.loads(token or "", salt=_MFA_SALT, max_age=MFA_TOKEN_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidCredentials("The sign-in has expired. Enter your username and password again.") from exc
    now = timezone.now()
    locked_until = None
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=data.get("u")).first()
        if user is None or not user.is_active or user.password[-16:] != data.get("p") or not user.mfa_enabled:
            raise InvalidCredentials("The sign-in has expired. Enter your username and password again.")
        if user.is_locked(now):
            locked_until = user.locked_until
        else:
            method = _check_second_factor(user, code)
            if method:
                _finish_login(ctx, user.username, user, now, mfa=method)
                if method == "recovery_code":
                    left = user.recovery_codes.filter(used_at__isnull=True).count()
                    from apps.notifications.services import notify_user

                    notify_user(user, kind="mfa_recovery_used", title="A recovery code was used to sign in",
                                body=f"{left} recovery code(s) left. If this was not you, tell the system administrator.",
                                link="/account/security")
                return user
            locked_until = _register_failure(ctx, user, now, "bad_mfa_code")
            _log_attempt(ctx, user.username, user, succeeded=False, reason="bad_mfa_code")
            record_event(ctx, action="auth.login", object_type="user", object_id=user.pk, outcome="failure",
                         actor=user, details={"reason": "bad_mfa_code"})
    if locked_until is not None:
        minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
        raise AccountLocked(f"Too many failed attempts. Try again in about {minutes} minute(s) "
                            "or ask an administrator to unlock the account.")
    raise InvalidCredentials("That code is not right. Check the time on your phone and try again.")


def _check_second_factor(user: User, code: str) -> str | None:
    """Returns "totp" or "recovery_code" when the code is valid (and consumes it), else None."""
    secret = mfa_lib.decrypt_secret(user.mfa_secret_encrypted)
    if secret:
        step = mfa_lib.verify_totp(secret, code, last_step=user.mfa_last_step)
        if step is not None:
            user.mfa_last_step = step
            user.save(update_fields=["mfa_last_step", "updated_at"])
            return "totp"
    rc = mfa_lib.normalise_recovery(code)
    if rc:
        for row in user.recovery_codes.filter(used_at__isnull=True):
            if mfa_lib.matches_recovery(rc, row.code_hash):
                row.used_at = timezone.now()
                row.save(update_fields=["used_at"])
                return "recovery_code"
    return None


def start_mfa_enrolment(user: User, session) -> dict:
    from apps.core.models import ClinicSettings

    secret = mfa_lib.new_secret()
    # Kept in the server-side session until confirmed with a working code; never stored half-set-up.
    session["mfa_pending"] = mfa_lib.encrypt_secret(secret)
    uri = mfa_lib.provisioning_uri(secret, user.username, ClinicSettings.get().facility_name)
    return {"secret": secret, "uri": uri, "qr_svg": mfa_lib.qr_svg(uri)}


def _new_recovery_codes(user: User) -> list[str]:
    codes = mfa_lib.new_recovery_codes()
    user.recovery_codes.all().delete()
    RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=mfa_lib.hash_recovery(c)) for c in codes])
    return codes


@transaction.atomic
def confirm_mfa_enrolment(ctx: ActorContext, user: User, session, code: str) -> list[str]:
    pending = session.get("mfa_pending")
    secret = mfa_lib.decrypt_secret(pending) if pending else None
    if not secret:
        raise BusinessValidationError("Start the set-up again.", fields={"code": ["Set-up expired."]})
    step = mfa_lib.verify_totp(secret, code, last_step=None)
    if step is None:
        raise BusinessValidationError("That code is not right. Check the time on your phone and try again.",
                                      fields={"code": ["Incorrect code."]})
    user = User.objects.select_for_update().get(pk=user.pk)
    user.mfa_secret_encrypted = mfa_lib.encrypt_secret(secret)
    user.mfa_enabled_at = timezone.now()
    user.mfa_last_step = step
    user.save(update_fields=["mfa_secret_encrypted", "mfa_enabled_at", "mfa_last_step", "updated_at"])
    codes = _new_recovery_codes(user)
    session.pop("mfa_pending", None)
    record_event(ctx, action="auth.mfa_enabled", object_type="user", object_id=user.pk)
    _security_email(user, "Two-step sign-in was turned on", "Two-step sign-in was turned on for your account.")
    from apps.notifications.services import notify_permission_holders

    # Administrators see every new enrolment, so one made by someone with a stolen password stands out.
    notify_permission_holders("users.manage", kind="mfa_enabled", title=f"{user.full_name} turned on two-step sign-in",
                              body="If this was not expected, reset their two-step sign-in and password.",
                              link="/admin/users", exclude_user=user)
    return codes


def _verify_current_factor(user: User, code: str) -> None:
    if not _check_second_factor(user, code):
        raise BusinessValidationError("That code is not right.", fields={"code": ["Incorrect code."]})


@transaction.atomic
def regenerate_recovery_codes(ctx: ActorContext, user: User, code: str) -> list[str]:
    user = User.objects.select_for_update().get(pk=user.pk)
    if not user.mfa_enabled:
        raise ConflictError("Two-step sign-in is not on.")
    _verify_current_factor(user, code)
    codes = _new_recovery_codes(user)
    record_event(ctx, action="auth.mfa_recovery_regenerated", object_type="user", object_id=user.pk)
    _security_email(user, "New recovery codes were made", "New recovery codes were made; the old ones no longer work.")
    return codes


@transaction.atomic
def disable_own_mfa(ctx: ActorContext, user: User, password: str, code: str) -> None:
    user = User.objects.select_for_update().get(pk=user.pk)
    if mfa_required_for(user):
        raise ConflictError("Two-step sign-in is required for your role and cannot be turned off.")
    if not user.check_password(password):
        raise BusinessValidationError("Password is incorrect.", fields={"password": ["Incorrect password."]})
    _verify_current_factor(user, code)
    _clear_mfa(user)
    record_event(ctx, action="auth.mfa_disabled", object_type="user", object_id=user.pk)
    _security_email(user, "Two-step sign-in was turned off", "Two-step sign-in was turned off for your account.")


def _clear_mfa(user: User) -> None:
    user.mfa_secret_encrypted = ""
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    user.save(update_fields=["mfa_secret_encrypted", "mfa_enabled_at", "mfa_last_step", "updated_at"])
    user.recovery_codes.all().delete()


@transaction.atomic
def admin_reset_mfa(ctx: ActorContext, user: User) -> int:
    """For a lost phone with no recovery codes. The user sets it up again at the next sign-in."""
    _forbid_self(ctx, user, "reset your own two-step sign-in here")
    _check_staff_scope(ctx, target=user)
    user = User.objects.select_for_update().get(pk=user.pk)
    _clear_mfa(user)
    ended = _revoke_all_sessions(user, UserSession.EndReason.REVOKED)
    record_event(ctx, action="user.mfa_reset", object_type="user", object_id=user.pk, details={"sessions_ended": ended})
    _security_email(user, "Your two-step sign-in was reset",
                    "An administrator reset two-step sign-in on your account. Set it up again at your next sign-in.")
    return ended
