import logging
import random
import time
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlparse

import requests
from django.db.models import Q
from django.utils import timezone as django_tz
from readability import Document

from apps.news.models import Article

logger = logging.getLogger(__name__)

TIMEOUT = 20
MAX_WORKERS = 10
DOMAIN_DELAY = 2.0  # min seconds between requests to same domain

# Real browser headers to avoid bot detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Error categories
ERR_TIMEOUT = "timeout"
ERR_HTTP_403 = "http_403"
ERR_HTTP_404 = "http_404"
ERR_HTTP_4XX = "http_4xx"
ERR_HTTP_5XX = "http_5xx"
ERR_TOO_SHORT = "too_short"
ERR_CONNECTION = "connection"
ERR_READABILITY = "readability"
ERR_OTHER = "other"


def _get_domain(url: str) -> str:
    """Extract domain from URL."""
    return urlparse(url).netloc.lower()


def _classify_error(error: Exception) -> tuple[str, str]:
    """Classify an extraction error into a category.

    Returns (category, message).
    """
    msg = str(error)

    if isinstance(error, requests.exceptions.Timeout):
        return ERR_TIMEOUT, msg
    if isinstance(error, requests.exceptions.ConnectionError):
        return ERR_CONNECTION, msg
    if isinstance(error, requests.exceptions.HTTPError):
        code = error.response.status_code if error.response is not None else 0
        if code == 403:
            return ERR_HTTP_403, f"{code} Forbidden"
        if code == 404:
            return ERR_HTTP_404, f"{code} Not Found"
        if 400 <= code < 500:
            return ERR_HTTP_4XX, f"{code} {msg}"
        if code >= 500:
            return ERR_HTTP_5XX, f"{code} {msg}"
        return ERR_OTHER, msg

    if "readability" in msg.lower() or "lxml" in msg.lower() or "parse" in msg.lower():
        return ERR_READABILITY, msg

    return ERR_OTHER, msg


def _strip_html(text: str) -> str:
    """Remove HTML tags, decode entities, collapse whitespace."""
    import re
    from html import unescape

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse spaces within lines
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _clean_for_xml(text: str) -> str:
    """Remove NULL bytes and XML-incompatible control characters."""
    import re
    # Remove NULL bytes and control chars except \t \n \r
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _fetch_and_extract(article_id: int, url: str) -> tuple[int, str, str | None, str | None]:
    """Download page and extract main content. Runs in a thread.

    Returns (article_id, clean_text, error_category, error_message).
    """
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()

        html = _clean_for_xml(resp.text)
        doc = Document(html)
        html_content = doc.summary()
        clean_text = _strip_html(html_content)

        if len(clean_text) < 50:
            return article_id, "", ERR_TOO_SHORT, f"Content too short ({len(clean_text)} chars)"

        return article_id, clean_text, None, None
    except Exception as e:
        category, message = _classify_error(e)
        return article_id, "", category, message


class ContentExtractor:
    """Extract full article text from URLs using readability.

    Uses per-domain throttling: at most one concurrent request per domain,
    with a cooldown of DOMAIN_DELAY seconds between requests to the same domain.
    """

    def __init__(self, workers: int = MAX_WORKERS, days: int = 30, stdout=None):
        self.workers = workers
        self.days = days
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def extract_new(self) -> tuple[int, int, list[str]]:
        """Extract content for articles not yet fetched.

        Only processes articles from the last self.days days (or with no date).
        Uses domain-based scheduling to avoid hammering any single host.

        Returns (total, extracted, errors).
        """
        cutoff = django_tz.now() - timedelta(days=self.days)
        articles = list(
            Article.objects.filter(content_fetched=False)
            .filter(Q(published__gte=cutoff) | Q(published__isnull=True))
            .exclude(url="")
            .values_list("id", "url", "rss_content")
        )

        if not articles:
            self._write("No articles to extract.\n")
            return 0, 0, []

        self._write(f"Extracting content for {len(articles)} articles...\n")

        # Group articles by domain
        domain_queues: dict[str, deque] = defaultdict(deque)
        rss_lookup: dict[int, str] = {}
        for aid, url, rss_content in articles:
            domain = _get_domain(url)
            domain_queues[domain].append((aid, url))
            rss_lookup[aid] = rss_content

        domains = list(domain_queues.keys())
        random.shuffle(domains)
        self._write(f"  {len(domains)} domains, {len(articles)} articles\n")

        extracted = 0
        fallback_count = 0
        errors: list[str] = []
        error_counts: Counter = Counter()
        done_count = 0

        domain_last_req: dict[str, float] = {}  # domain -> timestamp of last request
        active_domains: set[str] = set()  # domains with in-flight requests
        in_flight: dict = {}  # future -> (aid, domain)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while domain_queues or in_flight:
                # Submit new tasks for eligible domains
                now = time.monotonic()
                eligible = [
                    d for d in domains
                    if d in domain_queues
                    and d not in active_domains
                    and now - domain_last_req.get(d, 0) >= DOMAIN_DELAY
                ]
                random.shuffle(eligible)

                for domain in eligible[:self.workers - len(in_flight)]:
                    aid, url = domain_queues[domain].popleft()
                    if not domain_queues[domain]:
                        del domain_queues[domain]
                    active_domains.add(domain)
                    future = pool.submit(_fetch_and_extract, aid, url)
                    in_flight[future] = (aid, domain)

                # Collect finished results (non-blocking)
                finished = [f for f in in_flight if f.done()]
                for future in finished:
                    aid, domain = in_flight.pop(future)
                    active_domains.discard(domain)
                    domain_last_req[domain] = time.monotonic()

                    article_id, clean_text, err_category, err_message = future.result()
                    rss_content = rss_lookup.get(article_id, "")
                    done_count += 1

                    if err_category:
                        if rss_content and len(rss_content) >= 50:
                            Article.objects.filter(id=article_id).update(
                                content=rss_content,
                                content_fetched=True,
                                extract_error=f"[{err_category}] {err_message} (rss fallback)"[:500],
                            )
                            extracted += 1
                            fallback_count += 1
                        else:
                            errors.append(f"[{err_category}] {err_message}")
                            error_counts[err_category] += 1
                            Article.objects.filter(id=article_id).update(
                                content_fetched=True,
                                extract_error=f"[{err_category}] {err_message}"[:500],
                            )
                    else:
                        Article.objects.filter(id=article_id).update(
                            content=clean_text,
                            content_fetched=True,
                            extract_error="",
                        )
                        extracted += 1

                    if done_count % 100 == 0:
                        self._write(
                            f"  {done_count}/{len(articles)} processed "
                            f"({extracted} ok, {len(errors)} failed)\n"
                        )

                # If nothing finished and we couldn't submit, sleep briefly
                if not finished and len(in_flight) > 0:
                    time.sleep(0.1)
                elif not finished and not in_flight:
                    # All domains on cooldown, wait for shortest one
                    time.sleep(0.1)

        self._write(
            f"Done: {extracted}/{len(articles)} extracted"
        )
        if fallback_count:
            self._write(f" ({fallback_count} from RSS fallback)")
        if errors:
            self._write(f" ({len(errors)} failed)")
        self._write("\n")

        if error_counts:
            self._write("Error breakdown:\n")
            for cat, count in error_counts.most_common():
                self._write(f"  {cat}: {count}\n")

        return len(articles), extracted, errors
