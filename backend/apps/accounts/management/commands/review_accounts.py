"""
Daily account review: switch off accounts nobody has used for a long time (staff who left without
anyone telling the administrator), and tell the administrators who was switched off.

The number of days is set in System › Security (0 turns this off). Administrator accounts are included,
except that the last account able to manage users is never switched off.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import User
from apps.core.context import ActorContext
from apps.core.exceptions import ConflictError
from apps.core.models import SystemSettings


class Command(BaseCommand):
    help = "Switch off accounts unused for longer than the security policy allows."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run=False, **opts):
        days = SystemSettings.get().dormant_account_days
        if not days:
            self.stdout.write("dormant account review is off")
            return
        cutoff = timezone.now() - timedelta(days=days)
        dormant = User.objects.filter(is_active=True).filter(
            Q(last_login__lt=cutoff) | Q(last_login__isnull=True, created_at__lt=cutoff))
        ctx = ActorContext.system("review_accounts")
        names = []
        for user in dormant.order_by("username"):
            if dry_run:
                names.append(user.username)
                continue
            try:
                services.set_user_active(ctx, user, False)
            except ConflictError:
                continue  # the last administrator stays active
            names.append(user.username)
        if names and not dry_run:
            from apps.notifications.services import notify_permission_holders

            notify_permission_holders(
                "users.manage", kind="accounts_dormant", link="/admin/users?is_active=false",
                title=f"{len(names)} unused account(s) switched off",
                body=f"Not used for {days} days: {', '.join(names)[:200]}. Switch back on in Staff accounts if still needed.")
            notify_permission_holders(
                "staff.manage", kind="accounts_dormant", link="/admin/users?is_active=false",
                title=f"{len(names)} unused account(s) switched off", body=f"Not used for {days} days.")
        self.stdout.write(f"{'would switch off' if dry_run else 'switched off'}: {', '.join(names) or 'none'}")
