from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.core.management.commands.seed_demo import set_demo_dental_prices

# Demo accounts from older versions of seed_demo that a dental clinic does not have.
NON_DENTAL_DEMO_ACCOUNTS = ["doctor", "nurse", "lab", "pharmacy"]


class Command(BaseCommand):
    help = ("Bring an existing demo database up to date: plausible dental prices and no general-clinic demo "
            "accounts. Synthetic demo data only; refuses outside development without the flag.")

    def add_arguments(self, parser):
        parser.add_argument("--i-understand-this-is-not-production", action="store_true", dest="force")

    def handle(self, *args, force, **options):
        if not (settings.DEBUG or force):
            raise CommandError("Refusing to change prices outside development. See --help.")
        changed = set_demo_dental_prices(only_unpriced=False)
        gone = User.objects.filter(username__in=NON_DENTAL_DEMO_ACCOUNTS, is_active=True).update(is_active=False)
        self.stdout.write(f"Demo prices set on {changed} procedures; {gone} non-dental demo accounts deactivated.")
