from django.utils import timezone

from .models import Notification


def notify_user(user, *, kind: str, title: str, body: str = "", link: str = "", once: bool = False) -> Notification | None:
    if user is None or not user.is_active:
        return None
    if once and Notification.objects.filter(user=user, kind=kind, link=link[:255], read_at__isnull=True).exists():
        return None
    note = Notification.objects.create(user=user, kind=kind, title=title[:150], body=body[:255], link=link[:255])
    _email(user, note)
    return note


def _email(user, note) -> None:
    from .email import for_notification

    from django.db import transaction

    try:
        with transaction.atomic():  # a savepoint, so a failure here cannot spoil the caller's transaction
            for_notification(user, kind=note.kind, title=note.title, body=note.body, link=note.link)
    except Exception:  # noqa: BLE001 - email must never break the action that raised the notification
        import logging

        logging.getLogger(__name__).warning("Could not queue email for notification", exc_info=True)


def notify_permission_holders(permission_code: str, *, kind: str, title: str, body: str = "", link: str = "",
                              exclude_user=None, once: bool = False) -> int:
    """Notify everyone whose roles grant `permission_code`.

    once=True skips people who still have an unread notice of the same kind and link, so repeated
    checks (low stock, expiry, daily reminders) do not pile up identical notices."""
    from apps.accounts.models import User
    from apps.core.modules import disabled_permissions

    if permission_code in disabled_permissions():
        return 0  # its module is switched off: nobody does that work here
    users = User.objects.filter(is_active=True, roles__permissions__code=permission_code).distinct()
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
    if once:
        users = users.exclude(pk__in=Notification.objects.filter(kind=kind, link=link[:255], read_at__isnull=True)
                              .values("user_id"))
    users = list(users)
    notes = Notification.objects.bulk_create(
        [Notification(user=u, kind=kind, title=title[:150], body=body[:255], link=link[:255]) for u in users])
    for u, note in zip(users, notes):
        _email(u, note)
    return len(users)


def mark_read(user, ids=None) -> int:
    qs = Notification.objects.filter(user=user, read_at__isnull=True)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs.update(read_at=timezone.now())


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------
def current_announcements(user):
    from django.db.models import Case, Q, When

    from .models import Announcement

    today = timezone.localdate()
    role_ids = list(user.roles.values_list("pk", flat=True))
    qs = (Announcement.objects.filter(is_active=True, starts_on__lte=today)
          .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
          .filter(Q(roles__isnull=True) | Q(roles__in=role_ids))
          .filter(Q(department__isnull=True) | Q(department_id=user.department_id)))
    important_first = Case(When(level=Announcement.Level.IMPORTANT, then=0), default=1)
    return (qs.distinct().select_related("department", "created_by").prefetch_related("roles")
            .order_by(important_first, "-starts_on", "-created_at")[:10])


def save_announcement(ctx, obj, data: dict):
    from django.db import transaction

    from apps.accounts.models import Department, Role
    from apps.audit.services import record_event
    from apps.core.exceptions import BusinessValidationError

    from .models import Announcement

    with transaction.atomic():
        creating = obj is None
        obj = obj or Announcement(created_by=ctx.user)
        for key in ("title", "body", "level", "starts_on", "ends_on", "is_active"):
            if key in data:
                setattr(obj, key, data[key].strip() if isinstance(data[key], str) else data[key])
        if "department_id" in data:
            dept = None
            if data["department_id"]:
                dept = Department.objects.filter(pk=data["department_id"]).first()
                if dept is None:
                    raise BusinessValidationError("Unknown department.", fields={"department_id": ["Unknown."]})
            obj.department = dept
        if obj.ends_on and obj.starts_on and obj.ends_on < obj.starts_on:
            raise BusinessValidationError("The end date is before the start date.", fields={"ends_on": ["Too early."]})
        obj.save()
        if "role_ids" in data:
            roles = list(Role.objects.filter(pk__in=data["role_ids"]))
            if len(roles) != len(set(data["role_ids"])):
                raise BusinessValidationError("Unknown role.", fields={"role_ids": ["Unknown role."]})
            obj.roles.set(roles)
        record_event(ctx, action="announcement.create" if creating else "announcement.update",
                     object_type="announcement", object_id=obj.pk,
                     details={"title": obj.title, "active": obj.is_active})
    return obj
