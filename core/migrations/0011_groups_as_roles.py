from django.db import migrations, models

ADMIN_ROLE = "Administrator"
ROLE_NAMES = {
    "Sales Manager",
    "Sales Supervisor",
    "Sales Employee",
    "Marketing Manager",
    "Marketing Supervisor",
    "Marketing Employee",
    "Finance Manager",
    "Finance Supervisor",
    "Finance Employee",
    "Production Manager",
    "Production Supervisor",
    "Production Employee",
}


def forwards(apps, schema_editor):
    User = apps.get_model("core", "User")
    Group = apps.get_model("auth", "Group")
    db_alias = schema_editor.connection.alias
    groups = {
        group.name: group
        for group in Group.objects.using(db_alias).filter(name__in=ROLE_NAMES)
    }

    for user in User.objects.using(db_alias).all():
        if user.role == ADMIN_ROLE:
            user.is_superuser = True
            user.is_staff = True
            user.groups.clear()
        else:
            user.is_superuser = False
            user.is_staff = False
            group = groups.get(user.role)
            if group is None:
                user.groups.clear()
            else:
                user.groups.set([group])
        user.save(update_fields=["is_superuser", "is_staff"])


def backwards(apps, schema_editor):
    User = apps.get_model("core", "User")
    db_alias = schema_editor.connection.alias

    for user in User.objects.using(db_alias).all():
        if user.is_superuser:
            user.role = ADMIN_ROLE
        else:
            user.role = user.groups.values_list("name", flat=True).first() or ""
        user.save(update_fields=["role"])


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0010_custom_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "The groups this user belongs to. A user will get all permissions "
                    "granted to each of their groups."
                ),
                related_name="user_set",
                related_query_name="user",
                to="auth.group",
                verbose_name="groups",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="is_staff",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="is_superuser",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Designates that this user has all permissions without explicitly "
                    "assigning them."
                ),
                verbose_name="superuser status",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="user_permissions",
            field=models.ManyToManyField(
                blank=True,
                help_text="Specific permissions for this user.",
                related_name="user_set",
                related_query_name="user",
                to="auth.permission",
                verbose_name="user permissions",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name="user",
            name="role",
        ),
    ]
