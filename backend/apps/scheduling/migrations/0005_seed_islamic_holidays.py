"""Tentative Islamic public holidays (Proclamation 1334/2024, Art. 6). Dates follow moon sighting and are
announced shortly before; the clinic corrects them in the calendar when confirmed."""
import datetime

from django.db import migrations

NOTE = "Tentative: confirm against the official announcement before the day."
ROWS = [
    ("2026-03-20", "Eid al-Fitr"), ("2026-05-27", "Eid al-Adha (Arefa)"), ("2026-08-26", "Mawlid"),
    ("2027-03-10", "Eid al-Fitr"), ("2027-05-17", "Eid al-Adha (Arefa)"), ("2027-08-15", "Mawlid"),
]


def seed(apps, schema_editor):
    Holiday = apps.get_model("scheduling", "Holiday")
    for d, name in ROWS:
        Holiday.objects.get_or_create(date=datetime.date.fromisoformat(d), name=name,
                                      defaults={"kind": "religious", "tentative": True, "note": NOTE})


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0004_holidays")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
