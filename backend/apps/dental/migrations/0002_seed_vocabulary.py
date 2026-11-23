"""Starter chart findings and ICD-10 dental diagnoses, marked pending clinical review (docs/dental/clinical-review-log.md)."""

from django.db import migrations


def seed(apps, schema_editor):
    from apps.dental.starter_data import DIAGNOSIS_SOURCE, DIAGNOSIS_TERMS, FINDING_TYPES

    FindingType = apps.get_model("dental", "FindingType")
    Term = apps.get_model("dental", "DentalDiagnosisTerm")
    for code, name, kind, applies_to, symbol, colour, sort in FINDING_TYPES:
        FindingType.objects.get_or_create(code=code, defaults={
            "name": name, "kind": kind, "applies_to": applies_to, "symbol": symbol, "color": colour,
            "sort_order": sort})
    for code, term, category in DIAGNOSIS_TERMS:
        Term.objects.get_or_create(code_system="ICD-10", code=code, defaults={
            "term": term, "category": category, "source_version": DIAGNOSIS_SOURCE})


class Migration(migrations.Migration):
    dependencies = [("dental", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
