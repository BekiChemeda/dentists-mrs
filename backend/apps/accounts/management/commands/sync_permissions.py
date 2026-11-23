from django.core.management.base import BaseCommand

from apps.accounts.catalog import sync_catalog
from apps.accounts.models import Permission, Role


class Command(BaseCommand):
    help = "Insert missing permissions and default roles. Never removes customised role permissions."

    def handle(self, *args, **options):
        sync_catalog(Permission, Role)
        self.stdout.write(self.style.SUCCESS(
            f"Permissions: {Permission.objects.count()}  Roles: {Role.objects.count()}"
        ))
