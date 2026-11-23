"""
Tell system administrators when the health page has warnings (disk full, backups old, errors...).
Run daily by mrs-reminders.service; notifications (and emails, if set up) are not repeated while unread.
"""

from django.core.management.base import BaseCommand

from apps.core.system import health_snapshot, record_health_sample


class Command(BaseCommand):
    help = "Notify system administrators about health warnings."

    def handle(self, *args, **opts):
        from apps.notifications.services import notify_permission_holders

        snap = health_snapshot()
        record_health_sample(snap)  # one reading a day for the storage trend charts
        if not snap["warnings"]:
            self.stdout.write("healthy")
            return
        text = " ".join(snap["warnings"])
        n = notify_permission_holders("system.health.view", kind="system_health", once=True,
                                      title="The system needs attention", body=text[:255], link="/admin/system")
        self.stdout.write(f"{len(snap['warnings'])} warning(s); notified {n}")
