"""Create one demo login per department role in ROLES.

    python manage.py seed_users           # create what is missing (safe to repeat)
    python manage.py seed_users --reset   # also reset password and group of existing demo users

The username and password are the role in lower.dot.case: "Sales Manager" -> sales.manager.
These are demo logins; change the passwords on /manage/ before any real use.
"""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from core.roles import ROLES, apply_roles


class Command(BaseCommand):
    help = "Create one demo user per role in core.roles.ROLES (username = password)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="reset password and group membership of existing demo users")

    def handle(self, *args, **options):
        apply_roles(ROLES)
        created = reset = 0
        for role in ROLES:
            username = role.lower().replace(" and ", " ").replace(" ", ".")
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
            self.stdout.write(f"{username:26} {action}")
        self.stdout.write(self.style.SUCCESS(
            f"{created} created, {reset} reset, {len(ROLES) - created - reset} already existed"))
