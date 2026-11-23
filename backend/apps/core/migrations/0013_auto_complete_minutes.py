from django.db import migrations, models

from apps.core.concurrency import trigger_sql


class Migration(migrations.Migration):
    dependencies = [("core", "0012_cache_table")]

    operations = [
        migrations.AddField(
            model_name="clinicsettings",
            name="auto_complete_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunSQL(trigger_sql("core_clinic_settings", [
            "facility_name", "facility_level", "license_number", "address", "phone", "tin", "lab_billing_point",
            "show_ethiopian_calendar", "note_patient_card", "note_prescription", "note_consultation", "note_referral",
            "note_lab_report", "note_certificate", "opening_hours", "wait_alert_minutes", "allow_skip_triage",
            "auto_complete_minutes"]),
            migrations.RunSQL.noop),
    ]
