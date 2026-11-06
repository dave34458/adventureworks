from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0003_rename_report_table"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="report",
            name="uq_report_module_range",
        ),
    ]
