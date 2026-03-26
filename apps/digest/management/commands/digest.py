from datetime import date, datetime

from django.core.management.base import BaseCommand

from apps.core.services.ai import OpenAIError
from apps.digest.services import DigestService


class Command(BaseCommand):
    help = "Generate a daily news digest (7-step pipeline: collect → analyze → refine → generate → translate)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Digest date in YYYY-MM-DD format (default: today)",
        )
        parser.add_argument(
            "--lang",
            type=str,
            default=None,
            help="Comma-separated language codes to translate to (default: all non-default)",
        )

    def handle(self, *args, **options):
        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        languages = None
        if options["lang"]:
            languages = [lang.strip() for lang in options["lang"].split(",")]

        lang_label = ",".join(languages) if languages else "all"
        self.stdout.write(f"Generating digest for {digest_date} [translate: {lang_label}]...")

        try:
            service = DigestService()
            digest = service.run(digest_date=digest_date, languages=languages)
        except OpenAIError as e:
            self.stdout.write(self.style.ERROR(f"OpenAI error: {e}"))
            return
        except RuntimeError as e:
            self.stdout.write(self.style.WARNING(str(e)))
            return

        item_count = digest.items.count()
        translation_count = digest.translations.count()
        self.stdout.write(self.style.SUCCESS(
            f"Done: {digest.date} — {item_count} items, {translation_count} language(s)"
        ))
