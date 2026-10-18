from django.core.management.base import BaseCommand, CommandError

from core.roles import ROLES, apply_roles


class Command(BaseCommand):
    help = "Create or update the permission groups defined in core/roles.py (safe to run repeatedly)."

    def handle(self, *args, **opts):
        try:
            done = apply_roles(ROLES)
        except ValueError as e:
            raise CommandError(str(e))
        if done:
            self.stdout.write(f"Roles ready: {', '.join(done)}")
        else:
            self.stdout.write("No roles defined in core/roles.py yet (only the superadmin). Nothing to do.")
