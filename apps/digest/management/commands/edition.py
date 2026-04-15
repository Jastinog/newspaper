import sys
import time
from datetime import date, datetime

from django.core.management.base import BaseCommand

from apps.core.services.ai import OpenAIError
from apps.digest.services import EditionService

from ._styles import BOLD, CYAN, DIM, GREEN, RESET, YELLOW, arrow, fail, ok, skip


class Command(BaseCommand):
    help = "Generate a daily news digest using the Edition pipeline (collect -> plan -> write)"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None,
                            help="Digest date YYYY-MM-DD (default: today)")
        parser.add_argument("--lang", type=str, default=None,
                            help="Comma-separated language codes (default: all)")
        parser.add_argument("--items", type=int, default=None,
                            help="Override items per section (default: from config)")

    def handle(self, *args, **options):
        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        languages = None
        if options["lang"]:
            languages = [lang.strip() for lang in options["lang"].split(",")]

        self._total_stories = 0
        self._t0 = time.time()

        self.stdout.write(f"\n{BOLD} newspaper edition :: {digest_date}{RESET}\n")

        try:
            service = EditionService()
            service.run(
                digest_date=digest_date,
                languages=languages,
                items_per_section=options["items"],
                on_event=self._on_event,
            )
        except OpenAIError as e:
            self.stdout.write(fail(f"OpenAI: {e}"))
            sys.exit(1)
        except RuntimeError as e:
            self.stdout.write(fail(str(e)))
            sys.exit(1)

    def _on_event(self, event, **kw):
        if event == "collect":
            self.stdout.write(arrow("Collecting articles..."))
            snip = kw.get("snippet_tokens", "?")
            feeds = kw.get("feeds", "?")
            total = kw.get("total", kw["articles"])
            self.stdout.write(ok(
                f"{kw['articles']} articles from {feeds} feeds "
                f"{DIM}({total} total, snippet={snip} tok/article){RESET}"
            ))

        elif event == "plan":
            self._total_stories = kw["stories"]
            self.stdout.write("")
            self.stdout.write(arrow("Planning edition..."))
            self.stdout.write(ok(
                f"{CYAN}{kw['stories']}{RESET} stories planned "
                f"{DIM}{kw['tokens']:,} tok, ${kw['cost']:.4f}, "
                f"{kw['duration_ms'] // 1000}s{RESET}"
            ))
            self.stdout.write("")
            self.stdout.write(arrow(f"Writing {kw['stories']} items in parallel..."))

        elif event == "write_item":
            i = kw["index"]
            total = self._total_stories
            self.stdout.write(ok(
                f"({i:>3}/{total}) {kw['label'][:50]:50} "
                f"{DIM}[{kw['section']}] {kw.get('tokens', 0):>4} tok "
                f"${kw.get('cost', 0):.4f} | running: ${kw.get('running_cost', 0):.4f}{RESET}"
            ))

        elif event == "write_skip":
            i = kw["index"]
            total = self._total_stories
            reason = kw.get("reason", "")
            self.stdout.write(skip(
                f"({i:>3}/{total}) {kw['label'][:50]:50} {DIM}({reason}){RESET}"
            ))

        elif event == "done":
            elapsed = time.time() - self._t0
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.stdout.write("")
            self.stdout.write(
                f"{GREEN}{BOLD} :: Done!{RESET} "
                f"{kw['items']} items in {minutes}m {seconds}s"
            )
            if kw.get("failed"):
                self.stdout.write(f"   {YELLOW}{kw['failed']} failed{RESET}")
            self.stdout.write(
                f"   {BOLD}Total cost: ${kw.get('total_cost', 0):.4f}{RESET}"
            )
            self.stdout.write("")
