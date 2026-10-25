"""Create one demo login per scoped department role in ROLES.

    python manage.py seed_users                 # create what is missing (safe to repeat)
    python manage.py seed_users --reset         # also reset password and group of existing demo users
    python manage.py seed_users --reset --prune # also remove the old 17 demo users

The username and password are the role in lower.dot.case: "Sales Manager" -> sales.manager.
The single Administrator is the existing `admin` superuser; this command never creates or
changes a superuser. These are demo logins; change the passwords on /manage/ before real use.
"""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from core.roles import ROLES, apply_roles

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


class Command(BaseCommand):
    help = "Create one demo user per role in core.roles.ROLES (username = password)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="reset password and group membership of existing demo users")
        parser.add_argument("--prune", action="store_true",
                            help="remove demo users from the old 17-role matrix")

    def handle(self, *args, **options):
        apply_roles(ROLES, prune=True)
        created = reset = 0
        usernames = []
        for role in ROLES:
            username = role.lower().replace(" and ", " ").replace(" ", ".")
            usernames.append(username)
            user, is_new = User.objects.get_or_create(username=username)
            if is_new:
                created += 1
                action = "created"
            elif options["reset"]:
                reset += 1
                action = "reset"
            else:
                action = "exists"
            if is_new or options["reset"]:
                user.set_password(username)
                user.first_name = role
            user.groups.set([Group.objects.get(name=role)])
            user.save()
            self.stdout.write(f"{username:30} {action}")

        pruned = 0
        if options["prune"]:
            stale = User.objects.filter(username__in=LEGACY_DEMO_USERS).exclude(
                username__in=usernames)
            pruned = stale.count()
            stale.delete()

        self.stdout.write(self.style.SUCCESS(
            f"{created} created, {reset} reset, {pruned} pruned, "
            f"{len(ROLES) - created - reset} already existed"))
