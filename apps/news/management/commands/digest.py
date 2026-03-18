import logging
from datetime import date, datetime

from django.core.management.base import BaseCommand

from apps.news.services.digest import DigestService
from apps.news.services.openai_client import OpenAIError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Generate a daily news digest using OpenAI"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Digest date in YYYY-MM-DD format (default: today)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=60,
            help="Max number of recent articles to include",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=72,
            help="Look back N hours for articles",
        )

    def handle(self, *args, **options):
        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        self.stdout.write(f"Generating digest for {digest_date}...")

        try:
            service = DigestService(
                limit=options["limit"],
                hours=options["hours"],
            )
            digest = service.run(digest_date=digest_date)
        except OpenAIError as e:
            self.stdout.write(self.style.ERROR(f"OpenAI error: {e}"))
            return
        except RuntimeError as e:
            self.stdout.write(self.style.WARNING(str(e)))
            return

        sections = digest.sections.all()
        self.stdout.write(self.style.SUCCESS(
            f"Done: {digest.date} — {len(sections)} sections"
        ))
        self.stdout.write(f"  Headline: {digest.headline[:120]}...")
        for s in sections:
            self.stdout.write(f"  [{s.order}] {s.title} ({s.items.count()} items)")
