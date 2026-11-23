"""
Starting configuration for a new dental installation: switch off the medical modules a dental clinic does not use
(triage, laboratory, pharmacy). Run once by deploy/install.sh after `migrate`. The system administrator can switch
any of them back on from System > Modules.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Switch off triage, laboratory and pharmacy for a new dental clinic (only if nothing was recorded yet)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Apply even if the system already holds visits.")

    def handle(self, *args, **options):
        from apps.audit.services import record_event
        from apps.core.context import ActorContext
        from apps.core.models import SystemSettings
        from apps.scheduling.models import Visit

        if Visit.objects.exists() and not options["force"]:
            self.stdout.write("Visits already exist; modules left as they are (use --force to apply anyway).")
            return
        settings = SystemSettings.get()
        off = sorted(set(settings.disabled_modules or []) | {"triage", "laboratory", "pharmacy"})
        settings.disabled_modules = off
        settings.save(update_fields=["disabled_modules"])
        record_event(ActorContext.system("apply_dental_defaults"), action="system.dental_defaults",
                     object_type="module", details={"disabled": off})
        self.stdout.write(f"Modules switched off: {', '.join(off)}. Change them in System > Modules.")
