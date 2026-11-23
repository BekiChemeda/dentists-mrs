from django.core.management.base import BaseCommand

from apps.devices.models import Installation


class Command(BaseCommand):
    help = "Print this server's installation ID, which the supplier needs to issue the app licence."

    def handle(self, *args, **options):
        self.stdout.write(str(Installation.get().installation_id))
