import sys
import time
from datetime import date, datetime

from django.core.management.base import BaseCommand

from apps.core.services.ai import OpenAIError
from apps.digest.services import DigestService


# ── Arch-style formatting ────────────────────────────────────

BOLD = "\033[1m"
BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
RED = "\033[1;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[1;36m"
DIM = "\033[2m"
RESET = "\033[0m"


def arrow(msg):
    return f"{BLUE}::{BOLD} {msg}{RESET}"


def ok(msg):
    return f" {GREEN}[OK]{RESET} {msg}"


def fail(msg):
    return f" {RED}[FAIL]{RESET} {msg}"


def skip(msg):
    return f" {YELLOW}[SKIP]{RESET} {msg}"


def item(msg):
    return f" {DIM}->{RESET} {msg}"


class Command(BaseCommand):
    help = "Generate a daily news digest"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None,
                            help="Digest date YYYY-MM-DD (default: today)")
        parser.add_argument("--lang", type=str, default=None,
                            help="Comma-separated language codes (default: all)")

    def handle(self, *args, **options):
        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        languages = None
        if options["lang"]:
            languages = [l.strip() for l in options["lang"].split(",")]

        self._total_stories = 0
        self._t0 = time.time()

        self.stdout.write(f"\n{BOLD} newspaper digest :: {digest_date}{RESET}\n")

        try:
            service = DigestService()
            digest = service.run(
                digest_date=digest_date,
                languages=languages,
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
            self.stdout.write(ok(f"{kw['articles']} articles across {kw['sections']} sections"))

        elif event == "analyze_section":
            if kw.get("error"):
                self.stdout.write(fail(f"{kw['section']}"))
            else:
                self.stdout.write(item(
                    f"{kw['section']}: {kw['articles']} articles "
                    f"-> {CYAN}{kw['stories']}{RESET} stories"
                ))

        elif event == "analyze_done":
            self.stdout.write(ok(
                f"{kw['stories']} stories in {kw['sections']} sections "
                f"{DIM}(after dedup){RESET}"
            ))
            self._total_stories = kw["stories"]

        elif event == "generate_start":
            self.stdout.write("")
            self.stdout.write(arrow(f"Generating {kw['stories']} items..."))

        elif event == "generate_item":
            i = kw["index"]
            total = self._total_stories
            pct = i * 100 // total if total else 0
            self.stdout.write(ok(
                f"({i}/{total}) {DIM}{pct}%{RESET} "
                f"{kw['label']} {DIM}[{kw['section']}]{RESET}"
            ))

        elif event == "generate_skip":
            i = kw["index"]
            total = self._total_stories
            reason = kw.get("reason", "")
            self.stdout.write(skip(f"({i}/{total}) {kw['label']} {DIM}({reason}){RESET}"))

        elif event == "done":
            elapsed = time.time() - self._t0
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.stdout.write("")
            self.stdout.write(
                f"{GREEN}{BOLD} :: Done!{RESET} "
                f"{kw['items']} items in {minutes}m {seconds}s"
            )
            self.stdout.write("")
