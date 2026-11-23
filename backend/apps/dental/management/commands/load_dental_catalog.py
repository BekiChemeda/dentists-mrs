"""
Starter dental procedures (prices 0) and appointment types. Safe to run again: existing entries are left as they are.
The clinic must review names, durations and prices before use (docs/dental/clinical-review-log.md, R-06).
"""

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Load the starter dental procedure catalogue and appointment types (pending clinical review)."

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.dental.models import DentalProcedure
        from apps.dental.starter_data import APPOINTMENT_TYPES, PROCEDURES
        from apps.scheduling.models import AppointmentType

        made = 0
        for (code, name, category, minutes, tooth_req, surfaces, sessions, billing, fu_kind, fu_days,
             stock) in PROCEDURES:
            _, created = DentalProcedure.objects.get_or_create(code=code, defaults={
                "name": name, "category": category, "default_minutes": minutes, "tooth_requirement": tooth_req,
                "surfaces_allowed": surfaces, "typical_sessions": sessions, "billing_mode": billing,
                "follow_up_kind": fu_kind, "follow_up_days": fu_days, "consumes_stock": stock, "price": 0})
            made += created
        for n, (code, name, category, minutes) in enumerate(APPOINTMENT_TYPES):
            _, created = AppointmentType.objects.get_or_create(code=code, defaults={
                "name": name, "category": category, "default_minutes": minutes, "sort_order": n})
            made += created
        if options["verbosity"]:
            self.stdout.write(f"Dental catalogue: {made} new entries. Review names and set prices before use.")
