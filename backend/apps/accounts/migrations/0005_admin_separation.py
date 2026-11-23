"""
Separates system and clinic administration (and adds the Clinic director role):
- registers the new permissions and the clinic_director role;
- applies ROLE_CHANGES_0005 to the built-in roles, once;
- seeds the five triage destinations as departments (codes match existing triage records).
"""

from django.db import migrations

SEED_DEPARTMENTS = [
    ("adult_eopd", "Adult EOPD", True), ("pediatric_eopd", "Pediatric EOPD", True), ("opd1", "OPD 1", True),
    ("opd2", "OPD 2", True), ("labour_ward", "Labour ward", True), ("triage", "Triage", False),
    ("laboratory", "Laboratory", False), ("pharmacy", "Pharmacy", False), ("reception", "Reception", False),
    ("finance", "Finance", False), ("administration", "Administration", False),
]


def forward(apps, schema_editor):
    from apps.accounts.catalog import ROLE_CHANGES_0005, sync_catalog

    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    Department = apps.get_model("accounts", "Department")
    sync_catalog(Permission, Role)
    for code, change in ROLE_CHANGES_0005.items():
        role = Role.objects.filter(code=code, is_system=True).first()
        if role is None:
            continue
        role.permissions.add(*Permission.objects.filter(code__in=change["add"]))
        role.permissions.remove(*Permission.objects.filter(code__in=change["remove"]))
    for order, (code, name, triage) in enumerate(SEED_DEPARTMENTS):
        Department.objects.get_or_create(code=code, defaults={"name": name, "receives_triage": triage,
                                                              "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_department_user_start_date_user_department")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
