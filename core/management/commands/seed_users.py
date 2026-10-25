"""Create one demo login per scoped department role in ROLES.

    python manage.py seed_users                 # create what is missing (safe to repeat)
    python manage.py seed_users --reset         # also reset password and role of existing demo users
    python manage.py seed_users --reset --prune # also remove the old 17 demo users

The email and password use the role in lower.dot.case: "Sales Manager" ->
sales.manager@example.com / sales.manager. The single Administrator is the superuser
account; this command never creates or changes it. These are demo logins; change the
passwords on /manage/ before real use.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from core.roles import ROLES, apply_roles

User = get_user_model()

LEGACY_DEMO_USERS = {
    "executive",
    "finance.manager",
    "finance.staff",
    "sales.manager",
    "sales.staff",
    "marketing",
    "purchasing.manager",
    "purchasing.staff",
    "shipping.receiving",
    "production.manager",
    "production.staff",
    "production.control",
    "quality.assurance",
    "engineering.manager",
    "engineering.staff",
    "research.development",
    "tool.design",
}
LEGACY_DEMO_EMAILS = {f"{name}@example.com" for name in LEGACY_DEMO_USERS}


class Command(BaseCommand):
    help = "Create one demo user per role in core.roles.ROLES (email local part = password)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="reset password and role of existing demo users")
        parser.add_argument("--prune", action="store_true",
                            help="remove demo users from the old 17-role matrix")

    def handle(self, *args, **options):
        apply_roles(ROLES, prune=True)
        created = reset = 0
        emails = []
        for role in ROLES:
            local = role.lower().replace(" and ", " ").replace(" ", ".")
            email = f"{local}@example.com"
            emails.append(email)
            user, is_new = User.objects.get_or_create(
                email=email, defaults={"first_name": role})
            if is_new:
                created += 1
                action = "created"
            elif options["reset"]:
                reset += 1
                action = "reset"
            else:
                action = "exists"
            if is_new or options["reset"]:
                user.set_password(local)
            user.first_name = role
            user.is_staff = False
            user.is_superuser = False
            user.save()
            user.groups.set([Group.objects.get(name=role)])
            self.stdout.write(f"{email:40} {action}")

        pruned = 0
        if options["prune"]:
            stale = User.objects.filter(email__in=LEGACY_DEMO_EMAILS).exclude(
                email__in=emails)
            pruned = stale.count()
            stale.delete()

        self.stdout.write(self.style.SUCCESS(
            f"{created} created, {reset} reset, {pruned} pruned, "
            f"{len(ROLES) - created - reset} already existed"))
