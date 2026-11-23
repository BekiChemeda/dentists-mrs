"""Adds patients.status (mark a record inactive or deceased) to the built-in clinic administrator and doctor roles."""

from django.db import migrations


def forward(apps, schema_editor):
    from apps.accounts.catalog import ROLE_CHANGES_0010, sync_catalog

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    sync_catalog(Permission, Role)
    for code, change in ROLE_CHANGES_0010.items():
        role = Role.objects.filter(code=code, is_system=True).first()
        if role is not None:
            role.permissions.add(*Permission.objects.filter(code__in=change["add"]))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_row_version")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
