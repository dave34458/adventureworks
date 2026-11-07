from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0004_allow_multiple_report_ranges"),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="filters",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
