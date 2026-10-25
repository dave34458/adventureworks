from django.db import migrations


def remove_cost_recommendations(apps, schema_editor):
    Report = apps.get_model("core", "Report")
    for report in Report.objects.filter(module="cost"):
        payload = report.payload or {}
        if "recommendations" not in payload:
            continue
        payload.pop("recommendations")
        report.payload = payload
        report.save(update_fields=["payload"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_delete_privacyacknowledgment"),
    ]

    operations = [
        migrations.RunPython(remove_cost_recommendations, migrations.RunPython.noop),
    ]
