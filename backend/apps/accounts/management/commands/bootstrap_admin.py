from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.accounts.services import generate_temporary_password
from apps.audit.services import record_event
from apps.core.context import ActorContext


class Command(BaseCommand):
    help = (
        "Create the first system administrator with a one-time temporary password. "
        "Run once after installation; refuses to run if an administrator already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--first-name", default="System")
        parser.add_argument("--last-name", default="Administrator")

    @transaction.atomic
    def handle(self, *args, **opts):
        role = Role.objects.filter(code="system_admin").first()
        if role is None:
            raise CommandError("Role 'system_admin' missing. Run `manage.py migrate` first.")
        if User.objects.filter(roles=role, is_active=True).exists():
            raise CommandError("An active system administrator already exists. Nothing done.")
        username = opts["username"].strip().lower()
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"Username '{username}' is already taken.")

        temporary = generate_temporary_password()
        user = User(username=username, first_name=opts["first_name"], last_name=opts["last_name"],
                    must_change_password=True)
        user.set_password(temporary)
        user.full_clean(exclude=["password"])
        user.save()
        user.roles.add(role)
        record_event(ActorContext.system("bootstrap_admin"), action="user.create", object_type="user",
                     object_id=user.pk, details={"username": username, "roles": ["system_admin"],
                                                 "via": "bootstrap_admin"})
        self.stdout.write(self.style.SUCCESS(f"Created system administrator '{username}'."))
        self.stdout.write(f"Temporary password (shown once, must be changed at first sign-in): {temporary}")
