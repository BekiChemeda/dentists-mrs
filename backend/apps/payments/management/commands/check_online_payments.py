from django.core.management.base import BaseCommand

from apps.payments import services


class Command(BaseCommand):
    help = "Follow payment requests waiting on patients' phones, and catch late confirmations. Run every minute."

    def handle(self, *args, **options):
        if not services.licensed():
            return
        n = services.sweep()
        if n:
            self.stdout.write(f"Checked {n} payment request(s).")
