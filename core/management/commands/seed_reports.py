"""Build the default rolling 12-month snapshot for every report module.

Safe to run on every deploy: an existing range is skipped unless --force is given.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.test import RequestFactory

from core.models import Report, SalesOrderHeader
from core.utils import rolling_window
from core.views import REPORT_VIEWS, capture_snapshot


class Command(BaseCommand):
    help = "Generate the default rolling 12-month report snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Replace an existing snapshot for the same range.")

    def handle(self, *args, **options):
        window = rolling_window(SalesOrderHeader)
        if window is None:
            self.stdout.write("No sales data; no report snapshots created.")
            return

        start, end = window.trend_start.date(), window.last.date()
        user = get_user_model().objects.filter(is_superuser=True).first()
        if user is None:
            user = get_user_model()(username="system", is_superuser=True, is_staff=True)

        created = skipped = 0
        for module in REPORT_VIEWS:
            if not options["force"] and Report.objects.filter(
                    module=module, range_start=start, range_end=end).exists():
                skipped += 1
                continue
            request = RequestFactory().get(f"/{module}/")
            request.user = user
            snapshot = capture_snapshot(request, module, start, end, default=True)
            if snapshot is not None:
                created += 1
                self.stdout.write(f"{module}: {snapshot}")
            else:
                self.stdout.write(f"{module}: no data, skipped")
        self.stdout.write(self.style.SUCCESS(
            f"Report snapshots ready: {created} generated, {skipped} already present."))
