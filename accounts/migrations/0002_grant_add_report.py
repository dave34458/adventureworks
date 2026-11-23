from django.db import migrations

DEPARTMENTS = ("Sales", "Marketing", "Finance", "Production")


def grant_add_report(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permission = Permission.objects.filter(
        content_type__app_label="reporting", codename="add_report").first()
    if permission is None:
        return
    names = [f"{department} {kind}" for department in DEPARTMENTS
             for kind in ("Manager", "Admin")]
    for group in Group.objects.filter(name__in=names):
        group.permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("reporting", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(grant_add_report, migrations.RunPython.noop),
    ]
