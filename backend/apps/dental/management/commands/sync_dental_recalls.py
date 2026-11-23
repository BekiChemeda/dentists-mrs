"""Booked recalls follow their appointment: attended -> attended; cancelled or missed -> due again. Run daily."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Update booked recalls from their appointments."

    def handle(self, *args, **options):
        from apps.dental.services.recalls import sync_booked

        n = sync_booked()
        if options["verbosity"] > 1 or n:
            self.stdout.write(f"Recalls updated: {n}.")
