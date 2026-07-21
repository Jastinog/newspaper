import sys
import time
from datetime import date, datetime

from django.core.management.base import BaseCommand

from apps.digest.services import EmbeddingEdition

from ._styles import BOLD, CYAN, DIM, GREEN, RESET, arrow, fail, ok


class Command(BaseCommand):
    help = "Generate a daily digest by matching recent articles to section embeddings (no OpenAI)"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None,
                            help="Digest date YYYY-MM-DD (default: today)")
        parser.add_argument("--items", type=int, default=None,
                            help="Override items per section (default: from config)")

    def handle(self, *args, **options):
        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        self._t0 = time.time()
        self.stdout.write(f"\n{BOLD} newspaper edition :: {digest_date}{RESET}\n")

        try:
            service = EmbeddingEdition()
            service.run(
                digest_date=digest_date,
                per_section=options["items"],
                on_event=self._on_event,
            )
        except RuntimeError as e:
            self.stdout.write(fail(str(e)))
            sys.exit(1)

    def _on_event(self, event, **kw):
        if event == "collect":
            self.stdout.write(arrow("Collecting embedded articles..."))
            self.stdout.write(ok(
                f"{kw['articles']} articles "
                f"{DIM}({kw['chunks']} chunks in the lookback window){RESET}"
            ))
            self.stdout.write("")
            self.stdout.write(arrow("Matching articles to sections..."))

        elif event == "section":
            self.stdout.write(ok(
                f"{CYAN}{kw['count']:>3}{RESET} {kw['slug']}"
            ))

        elif event == "done":
            elapsed = time.time() - self._t0
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.stdout.write("")
            self.stdout.write(
                f"{GREEN}{BOLD} :: Done!{RESET} "
                f"{kw['items']} items across {kw['sections']} sections "
                f"in {minutes}m {seconds}s"
            )
            self.stdout.write("")
