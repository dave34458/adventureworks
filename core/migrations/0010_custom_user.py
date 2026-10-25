from django.db import migrations

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


def _unique_email(value, username, user_id, used):
    email = (value or "").strip().lower()
    if not email:
        email = f"{(username or 'user').strip().lower()}@example.com"
    if email in used:
        local, _, domain = email.partition("@")
        email = f"{local}+{user_id}@{domain or 'example.com'}"
        suffix = 2
        while email in used:
            email = f"{local}+{user_id}-{suffix}@{domain or 'example.com'}"
            suffix += 1
    used.add(email)
    return email


def forwards(apps, schema_editor):
    connection = schema_editor.connection
    tables = connection.introspection.table_names()
    if "auth_user" not in tables:
        return

    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, "auth_user")
        }
    if "username" not in columns:
        return

    roles = {}
    if "auth_user_groups" in tables and "auth_group" in tables:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ug.user_id, g.name FROM auth_user_groups ug "
                "JOIN auth_group g ON g.id = ug.group_id ORDER BY g.name"
            )
            for user_id, group_name in cursor.fetchall():
                roles.setdefault(user_id, group_name)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, password, last_login, first_name, last_name, email, "
            "is_active, is_superuser, username FROM auth_user ORDER BY id"
        )
        rows = cursor.fetchall()

    used = set()
    users = []
    for user_id, password, last_login, first_name, last_name, email, active, superuser, username in rows:
        role = ADMIN_ROLE if superuser else roles.get(user_id, "")
        if role not in ROLE_NAMES and role != ADMIN_ROLE:
            role = ""
        users.append((
            user_id,
            password,
            last_login,
            _unique_email(email, username, user_id, used),
            first_name or "",
            last_name or "",
            active,
            role,
        ))

    quote = schema_editor.quote_name
    schema_editor.execute("DROP TABLE IF EXISTS auth_user_new")
    schema_editor.execute(f"""
        CREATE TABLE {quote("auth_user_new")} (
            {quote("id")} integer NOT NULL PRIMARY KEY AUTOINCREMENT,
            {quote("password")} varchar(128) NOT NULL,
            {quote("last_login")} datetime NULL,
            {quote("email")} varchar(254) NOT NULL UNIQUE,
            {quote("first_name")} varchar(150) NOT NULL,
            {quote("last_name")} varchar(150) NOT NULL,
            {quote("is_active")} bool NOT NULL,
            {quote("role")} varchar(80) NOT NULL
        )
    """)
    insert = (
        f"INSERT INTO {quote('auth_user_new')} "
        f"({quote('id')}, {quote('password')}, {quote('last_login')}, "
        f"{quote('email')}, {quote('first_name')}, {quote('last_name')}, "
        f"{quote('is_active')}, {quote('role')}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    )
    for user in users:
        schema_editor.execute(insert, user)
    schema_editor.execute("DROP TABLE IF EXISTS auth_user_groups")
    schema_editor.execute("DROP TABLE IF EXISTS auth_user_user_permissions")
    schema_editor.execute(f"DROP TABLE {quote('auth_user')}")
    schema_editor.execute(
        f"ALTER TABLE {quote('auth_user_new')} RENAME TO {quote('auth_user')}"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_report_payload_only"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
