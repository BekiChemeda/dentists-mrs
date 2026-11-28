from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0004_online_payments"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="amount_tendered",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="balance_after",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
    ]
