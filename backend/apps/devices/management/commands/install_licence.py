from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.context import ActorContext
from apps.core.exceptions import DomainError
from apps.devices import services


class Command(BaseCommand):
    help = "Install the app licence file received from the supplier."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the licence file (one line starting MRSL1.)")

    def handle(self, *args, **options):
        text = Path(options["file"]).read_text().strip()
        try:
            status = services.install_licence(ActorContext.system("manage.py install_licence"), text)
        except DomainError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Licence installed for {status['clinic_name']}: app {'included' if status['mobile_app'] else 'not included'}, "
            f"{status['max_devices']} phones, until {status['expires_on']}."))
