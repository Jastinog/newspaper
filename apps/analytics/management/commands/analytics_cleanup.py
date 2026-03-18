from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.analytics.models import PageView


class Command(BaseCommand):
    help = "Delete old analytics data (bots > 7 days, all > 90 days)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--bot-days",
            type=int,
            default=7,
            help="Delete bot records older than N days (default: 7)",
        )
        parser.add_argument(
            "--max-days",
            type=int,
            default=90,
            help="Delete all records older than N days (default: 90)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without deleting",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        bot_cutoff = now - timedelta(days=options["bot_days"])
        max_cutoff = now - timedelta(days=options["max_days"])

        bot_qs = PageView.objects.filter(is_bot=True, timestamp__lt=bot_cutoff)
        old_qs = PageView.objects.filter(timestamp__lt=max_cutoff)

        bot_count = bot_qs.count()
        old_count = old_qs.count()

        if options["dry_run"]:
            self.stdout.write(f"Would delete {bot_count} bot records (>{options['bot_days']}d)")
            self.stdout.write(f"Would delete {old_count} old records (>{options['max_days']}d)")
            return

        deleted_bots, _ = bot_qs.delete()
        deleted_old, _ = old_qs.delete()
        total = deleted_bots + deleted_old

        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted_bots} bot + {deleted_old} old = {total} total records"
        ))
