"""Send queued emails (run every minute by deploy/systemd/mrs-email.timer). Does nothing while email is off."""

from django.core.management.base import BaseCommand

from apps.notifications.email import send_outbox


class Command(BaseCommand):
    help = "Send emails waiting in the outbox, retrying failed ones later."

    def handle(self, *args, **opts):
        result = send_outbox()
        if result.get("sent") or result.get("failed") or self.verbosity > 1:
            self.stdout.write(str(result))
