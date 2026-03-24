from django.core.management.base import BaseCommand
from apps.feeds.models import Article
from apps.crawler.services.extractor import _fetch_and_extract


class Command(BaseCommand):
    help = "Debug content extraction: test on a sample or inspect past failures"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test", type=int, default=0, metavar="N",
            help="Extract N random unfetched articles with verbose output",
        )
        parser.add_argument(
            "--retry", type=int, default=0, metavar="N",
            help="Retry N previously failed articles with verbose output",
        )
        parser.add_argument(
            "--url", type=str, default="",
            help="Test extraction on a specific URL",
        )
        parser.add_argument(
            "--errors", action="store_true",
            help="Show breakdown of stored extraction errors",
        )
        parser.add_argument(
            "--errors-detail", type=str, default="", metavar="CATEGORY",
            help="Show sample URLs for a specific error category (e.g. timeout, http_403)",
        )

    def handle(self, *args, **options):
        if options["errors"]:
            self._show_errors()
        elif options["errors_detail"]:
            self._show_error_detail(options["errors_detail"])
        elif options["url"]:
            self._test_url(options["url"])
        elif options["test"]:
            self._test_sample(options["test"])
        elif options["retry"]:
            self._retry_failed(options["retry"])
        else:
            self.stderr.write("Specify --test N, --retry N, --url URL, --errors, or --errors-detail CATEGORY")

    def _show_errors(self):
        from collections import Counter

        failed = Article.objects.filter(
            content_fetched=True, extract_error__gt=""
        ).values_list("extract_error", flat=True)

        if not failed:
            self.stdout.write("No extraction errors stored.\n")
            return

        categories = Counter()
        for err in failed:
            if err.startswith("[") and "]" in err:
                cat = err[1:err.index("]")]
            else:
                cat = "unknown"
            categories[cat] += 1

        total = sum(categories.values())
        self.stdout.write(f"\nExtraction errors: {total} total\n")
        self.stdout.write("-" * 40 + "\n")
        for cat, count in categories.most_common():
            pct = count / total * 100
            self.stdout.write(f"  {cat:20s} {count:5d}  ({pct:.1f}%)\n")

    def _show_error_detail(self, category):
        articles = (
            Article.objects.filter(
                content_fetched=True,
                extract_error__startswith=f"[{category}]",
            )
            .select_related("feed")
            .order_by("-published")[:20]
        )

        if not articles:
            self.stdout.write(f"No errors with category '{category}'.\n")
            return

        self.stdout.write(f"\nSample articles with [{category}] errors:\n")
        self.stdout.write("-" * 80 + "\n")
        for a in articles:
            self.stdout.write(f"  Feed:  {a.feed.title}\n")
            self.stdout.write(f"  Title: {a.title[:80]}\n")
            self.stdout.write(f"  URL:   {a.url}\n")
            self.stdout.write(f"  Error: {a.extract_error}\n")
            self.stdout.write("\n")

    def _test_url(self, url):
        self.stdout.write(f"Testing: {url}\n")
        self.stdout.write("-" * 80 + "\n")

        _id, text, _og, _imgs, err_cat, err_msg = _fetch_and_extract(0, url)

        if err_cat:
            self.stdout.write(self.style.ERROR(f"FAILED [{err_cat}]: {err_msg}\n"))
        else:
            self.stdout.write(self.style.SUCCESS(f"OK — {len(text)} chars extracted\n"))
            preview = text[:500]
            self.stdout.write(f"\nPreview:\n{preview}\n")
            if len(text) > 500:
                self.stdout.write(f"... ({len(text) - 500} more chars)\n")

    def _test_sample(self, n):
        articles = list(
            Article.objects.filter(content_fetched=False)
            .exclude(url="")
            .order_by("?")
            .values_list("id", "url", "title", "feed__title")[:n]
        )

        if not articles:
            self.stdout.write("No unfetched articles to test.\n")
            return

        self.stdout.write(f"Testing {len(articles)} articles...\n\n")

        ok = 0
        fail = 0
        for aid, url, title, feed_title in articles:
            self.stdout.write(f"[{feed_title}] {title[:60]}\n")
            self.stdout.write(f"  URL: {url}\n")

            _id, text, _og, _imgs, err_cat, err_msg = _fetch_and_extract(aid, url)

            if err_cat:
                self.stdout.write(self.style.ERROR(f"  FAIL [{err_cat}]: {err_msg}\n"))
                fail += 1
            else:
                self.stdout.write(self.style.SUCCESS(f"  OK — {len(text)} chars\n"))
                ok += 1
            self.stdout.write("\n")

        self.stdout.write(f"Results: {ok} ok, {fail} failed out of {len(articles)}\n")

    def _retry_failed(self, n):
        articles = list(
            Article.objects.filter(
                content_fetched=True,
                extract_error__gt="",
            )
            .select_related("feed")
            .order_by("?")[:n]
        )

        if not articles:
            self.stdout.write("No failed articles to retry.\n")
            return

        self.stdout.write(f"Retrying {len(articles)} failed articles...\n\n")

        ok = 0
        fail = 0
        for a in articles:
            self.stdout.write(f"[{a.feed.title}] {a.title[:60]}\n")
            self.stdout.write(f"  URL: {a.url}\n")
            self.stdout.write(f"  Previous error: {a.extract_error}\n")

            _id, text, _og, _imgs, err_cat, err_msg = _fetch_and_extract(a.id, a.url)

            if err_cat:
                self.stdout.write(self.style.ERROR(f"  STILL FAILS [{err_cat}]: {err_msg}\n"))
                fail += 1
            else:
                self.stdout.write(self.style.SUCCESS(f"  NOW OK — {len(text)} chars\n"))
                Article.objects.filter(id=a.id).update(
                    content=text,
                    extract_error="",
                )
                ok += 1
            self.stdout.write("\n")

        self.stdout.write(f"Results: {ok} fixed, {fail} still failing out of {len(articles)}\n")
