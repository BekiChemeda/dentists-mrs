import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clinical", "0013_prescription_visit_backfill")]

    operations = [
        migrations.AlterField(
            model_name="prescription",
            name="visit",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="prescriptions",
                                    to="scheduling.visit"),
        ),
        migrations.AddConstraint(
            model_name="prescription",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("dental_encounter__isnull", True), ("encounter__isnull", False)
                    ),
                    models.Q(
                        ("dental_encounter__isnull", False), ("encounter__isnull", True)
                    ),
                    _connector="OR",
                ),
                name="prescription_one_encounter",
            ),
        ),
    ]
