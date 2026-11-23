from django.db import migrations


def seed(apps, schema_editor):
    from apps.clinical.icd10_common import COMMON_ICD10

    IcdCode = apps.get_model("clinical", "IcdCode")
    for code, title in COMMON_ICD10:
        IcdCode.objects.update_or_create(code=code, defaults={"title": title, "is_common": True})


class Migration(migrations.Migration):
    dependencies = [("clinical", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
