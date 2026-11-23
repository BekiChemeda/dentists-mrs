"""Dental MRS orthodontics: the dental.ortho.manage permission, given to the built-in dentist role."""

from django.db import migrations


def forward(apps, schema_editor):
    from apps.accounts.catalog import ROLE_CHANGES_0015, sync_catalog

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    sync_catalog(Permission, Role)
    for code, change in ROLE_CHANGES_0015.items():
        role = Role.objects.filter(code=code, is_system=True).first()
        if role is not None:
            role.permissions.add(*Permission.objects.filter(code__in=change["add"]))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0014_dental_permissions")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
