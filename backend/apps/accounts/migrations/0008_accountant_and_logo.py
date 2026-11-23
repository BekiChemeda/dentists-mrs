"""
Adds the built-in Accountant role and the branding.manage permission (clinic logo), and gives that
permission to the built-in system administrator and clinic administrator roles, once.
"""

from django.db import migrations


def forward(apps, schema_editor):
    from apps.accounts.catalog import ROLE_CHANGES_0008, sync_catalog

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    sync_catalog(Permission, Role)
    for code, change in ROLE_CHANGES_0008.items():
        role = Role.objects.filter(code=code, is_system=True).first()
        if role is None:
            continue
        role.permissions.add(*Permission.objects.filter(code__in=change["add"]))
        role.permissions.remove(*Permission.objects.filter(code__in=change["remove"]))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0007_email")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
