from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS core_cache")


class Migration(migrations.Migration):
    """Shared cache for request limits; replaces the per-worker in-memory cache."""

    dependencies = [("core", "0011_disabled_modules")]
    operations = [migrations.RunPython(create_cache_table, drop_cache_table)]
