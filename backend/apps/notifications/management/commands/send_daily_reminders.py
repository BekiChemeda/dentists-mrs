"""Daily reminders: medicines near expiry, tomorrow's appointments and follow-ups not yet booked.

Run once a day (for example from cron at 17:00, Africa/Addis_Ababa):
    python manage.py send_daily_reminders
Safe to run more than once: a reminder is not repeated while the earlier one is still unread.
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.clinical.models import Encounter
from apps.inventory.services import expiring_batches
from apps.notifications.services import notify_permission_holders, notify_user
from apps.scheduling.models import Appointment

EXPIRY_WARNING_DAYS = 90


class Command(BaseCommand):
    help = "Send near-expiry, appointment and follow-up reminders to staff."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Treat this date (YYYY-MM-DD) as today; for testing.")

    def handle(self, *args, **opts):
        today = datetime.date.fromisoformat(opts["date"]) if opts.get("date") else timezone.localdate()
        tomorrow = today + datetime.timedelta(days=1)
        sent = {"expiry": 0, "appointments": 0, "follow_up": 0}

        # Stock near expiry (or already expired and still on the shelf).
        for batch in expiring_batches(EXPIRY_WARNING_DAYS):
            expired = batch.expiry_date < today
            sent["expiry"] += notify_permission_holders(
                "inventory.manage", kind="expiry", once=True, link=f"/inventory?batch={batch.pk}",
                title=f"{'Expired' if expired else 'Expires soon'}: {batch.item.name}",
                body=f"Batch {batch.batch_number}, {batch.on_hand.normalize():f} {batch.item.unit}, "
                     f"expiry {batch.expiry_date:%Y-%m-%d}.")

        # Tomorrow's appointments: a count for reception, each doctor's own list.
        appts = list(Appointment.objects.filter(
            scheduled_at__date=tomorrow,
            status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED]).select_related("patient", "doctor"))
        if appts:
            unconfirmed = sum(1 for a in appts if a.status == Appointment.Status.SCHEDULED)
            sent["appointments"] += notify_permission_holders(
                "appointments.manage", kind="appointment_reminder", once=True, link=f"/appointments?date={tomorrow}",
                title=f"{len(appts)} appointment(s) tomorrow",
                body=f"{unconfirmed} not yet confirmed. Call the patients to confirm." if unconfirmed else "All confirmed.")
            by_doctor = {}
            for a in appts:
                by_doctor.setdefault(a.doctor, []).append(a)
            for doctor, rows in by_doctor.items():
                names = ", ".join(f"{a.scheduled_at.astimezone(timezone.get_current_timezone()):%H:%M} {a.patient.full_name}"
                                  for a in sorted(rows, key=lambda a: a.scheduled_at))
                if notify_user(doctor, kind="appointment_reminder", title=f"Your appointments tomorrow: {len(rows)}",
                               body=names, link=f"/appointments?date={tomorrow}&doctor={doctor.pk}", once=True):
                    sent["appointments"] += 1

        # Follow-ups the doctor asked for tomorrow that nobody has booked.
        booked = set(Appointment.objects.filter(scheduled_at__date=tomorrow).exclude(
            status=Appointment.Status.CANCELLED).values_list("patient_id", flat=True))
        for enc in Encounter.objects.filter(follow_up_date=tomorrow, status=Encounter.Status.SIGNED).select_related("patient", "doctor"):
            if enc.patient_id in booked:
                continue
            sent["follow_up"] += notify_permission_holders(
                "appointments.manage", kind="follow_up", once=True, link=f"/patients/{enc.patient_id}?tab=appointments",
                title=f"Follow-up due tomorrow: {enc.patient.full_name}",
                body=f"Requested by Dr. {enc.doctor.full_name}; no appointment is booked. Phone {enc.patient.phone or 'not recorded'}.")
        self.stdout.write(", ".join(f"{k}: {v}" for k, v in sent.items()))
