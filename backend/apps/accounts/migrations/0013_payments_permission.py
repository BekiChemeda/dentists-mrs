"""Adds payments.gateway.manage (set up payments by phone and their keys) to the built-in system administrator."""

from django.db import migrations


def forward(apps, schema_editor):
    from apps.accounts.catalog import ROLE_CHANGES_0013, sync_catalog

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    sync_catalog(Permission, Role)
    for code, change in ROLE_CHANGES_0013.items():
        role = Role.objects.filter(code=code, is_system=True).first()
        if role is not None:
            role.permissions.add(*Permission.objects.filter(code__in=change["add"]))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_session_device")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
