from django.db import migrations


def seed(apps, schema_editor):
    from apps.accounts.catalog import sync_catalog

    sync_catalog(apps.get_model("accounts", "Permission"), apps.get_model("accounts", "Role"))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
