from django.db import migrations


def visit_from_encounter(apps, schema_editor):
    """Existing prescriptions all came from medical consultations: their visit is the consultation's visit."""
    Prescription = apps.get_model("clinical", "Prescription")
    Encounter = apps.get_model("clinical", "Encounter")
    for rx in Prescription.objects.filter(visit__isnull=True).only("id", "encounter_id"):
        visit_id = Encounter.objects.filter(pk=rx.encounter_id).values_list("visit_id", flat=True).first()
        Prescription.objects.filter(pk=rx.pk).update(visit_id=visit_id)


class Migration(migrations.Migration):
    dependencies = [("clinical", "0012_dental_support")]

    operations = [migrations.RunPython(visit_from_encounter, migrations.RunPython.noop)]
