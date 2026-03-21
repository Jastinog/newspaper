from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.analytics.models import Client, Session


class Command(BaseCommand):
    help = "Delete old analytics data (bot sessions > 7 days, all > 90 days)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--bot-days",
            type=int,
            default=7,
            help="Delete bot sessions older than N days (default: 7)",
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

        # Bot sessions older than bot_cutoff (activities cascade)
        bot_sessions = Session.objects.filter(
            client__is_bot=True, started_at__lt=bot_cutoff
        )
        # All sessions older than max_cutoff (activities cascade)
        old_sessions = Session.objects.filter(started_at__lt=max_cutoff)
        # Orphaned clients with no remaining sessions
        orphaned_clients = Client.objects.filter(sessions__isnull=True)

        if options["dry_run"]:
            self.stdout.write(f"Would delete {bot_sessions.count()} bot sessions (>{options['bot_days']}d)")
            self.stdout.write(f"Would delete {old_sessions.count()} old sessions (>{options['max_days']}d)")
            self.stdout.write(f"Would delete {orphaned_clients.count()} orphaned clients")
            return

        deleted_bot_sessions, _ = bot_sessions.delete()
        deleted_old_sessions, _ = old_sessions.delete()
        deleted_clients, _ = orphaned_clients.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted_bot_sessions} bot sessions "
            f"+ {deleted_old_sessions} old sessions "
            f"+ {deleted_clients} orphaned clients"
        ))
