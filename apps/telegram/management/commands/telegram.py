from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.digest.models import Digest, DigestItem
from apps.telegram.models import TelegramChannel
from apps.telegram.services import TelegramService, publish_to_all_channels


class Command(BaseCommand):
    help = "Publish digest to Telegram channels"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Digest date in YYYY-MM-DD format (default: today)",
        )
        parser.add_argument(
            "--channel",
            type=str,
            default=None,
            help="Channel name or chat_id to post to (default: all active)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be posted without sending",
        )

    def handle(self, *args, **options):
        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        digest = Digest.objects.filter(date=digest_date, stage=Digest.Stage.DONE).first()
        if not digest:
            self.stdout.write(self.style.WARNING(f"No completed digest for {digest_date}"))
            return

        if options["dry_run"]:
            self._dry_run(digest, options["channel"])
            return

        if options["channel"]:
            channel = self._find_channel(options["channel"])
            if not channel:
                self.stdout.write(self.style.ERROR(f"Channel not found: {options['channel']}"))
                return
            service = TelegramService(channel)
            post = service.publish_digest(digest)
            self._print_result(post)
        else:
            results = publish_to_all_channels(digest)
            if not results:
                self.stdout.write(self.style.WARNING("No channels to post to"))
                return
            for post in results:
                self._print_result(post)

    def _find_channel(self, query):
        return (
            TelegramChannel.objects
            .filter(is_active=True)
            .filter(Q(name=query) | Q(chat_id=query))
            .select_related("language")
            .first()
        )

    def _print_result(self, post):
        if post.status == "success":
            self.stdout.write(self.style.SUCCESS(
                f"{post.channel.name}: {post.items_posted} items posted"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{post.channel.name}: FAILED — {post.error_message}"
            ))

    def _dry_run(self, digest, channel_filter):
        channels = TelegramChannel.objects.filter(is_active=True).select_related("language")
        if channel_filter:
            channels = channels.filter(Q(name=channel_filter) | Q(chat_id=channel_filter))

        if not channels:
            self.stdout.write(self.style.WARNING("No matching active channels"))
            return

        for channel in channels:
            service = TelegramService(channel)
            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(self.style.HTTP_INFO(f"Channel: {channel.name} ({channel.chat_id})"))
            self.stdout.write(f"Language: {channel.language.code}, Top N: {channel.top_n}")
            self.stdout.write(f"Bot token: {'from env' if not channel.bot_token else 'per-channel'}")
            self.stdout.write(f"\n{service._format_header(digest)}\n")

            items = (
                DigestItem.objects
                .filter(digest=digest)
                .select_related("section", "image")
                .prefetch_related("translations", "translations__language")
                .order_by("-importance", "-freshness")
                [: channel.top_n]
            )
            for item in items:
                self.stdout.write(f"\n{service._format_item(item)}")

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS("Dry run complete — nothing was sent"))
