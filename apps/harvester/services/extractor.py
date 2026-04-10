import logging
import random
import re
import time
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import requests
from django.db.models import Q
from django.utils import timezone as django_tz
from markdownify import markdownify as md
from readability import Document

from apps.feed.models import Article, ArticleImage, ArticleImageSource, ArticlePipeline
from .http import get_domain, random_headers
from .throttle import acquire_domain, release_domain

logger = logging.getLogger(__name__)

TIMEOUT = 20
MAX_WORKERS = 10
EXTRACT_BATCH_SIZE = 10


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


def _html_to_markdown(html: str) -> str:
    """Convert HTML to clean Markdown, preserving structure."""
    text = md(
        html,
        heading_style="atx",
        bullets="-",
        escape_misc=True,
        strip=["img", "script", "style", "iframe"],
    )
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_for_xml(text: str) -> str:
    """Remove NULL bytes and XML-incompatible control characters."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _extract_og_image(html: str) -> str:
    """Extract og:image URL from HTML meta tags."""
    match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if match:
        return match.group(1)
    # Try reversed attribute order: content before property
    match = re.search(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        html, re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return ""


MAX_CONTENT_IMAGES = 3


def _extract_content_images(html_content: str) -> list[str]:
    """Extract image URLs from readability-processed HTML content."""
    urls = []
    seen = set()
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE):
        url = match.group(1)
        if url in seen or url.startswith("data:"):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= MAX_CONTENT_IMAGES:
            break
    return urls


def fetch_and_extract(article_id: int, url: str) -> tuple[int, str, str, list[str], str | None, str | None]:
    """Download page and extract main content. Runs in a thread.

    Returns (article_id, clean_text, og_image, content_images, error_category, error_message).
    """
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=random_headers())
        resp.raise_for_status()

        html = _clean_for_xml(resp.text).strip()
        if not html:
            return article_id, "", "", [], ERR_TOO_SHORT, "Empty response body"

        og_image = _extract_og_image(html)

        doc = Document(html)
        html_content = doc.summary(html_partial=True)
        content_images = _extract_content_images(html_content)
        clean_text = _html_to_markdown(html_content)

        if len(clean_text) < 50:
            return article_id, "", og_image, content_images, ERR_TOO_SHORT, f"Content too short ({len(clean_text)} chars)"

        return article_id, clean_text, og_image, content_images, None, None
    except Exception as e:
        category, message = _classify_error(e)
        return article_id, "", "", [], category, message


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

    def _get_og_source(self):
        if not hasattr(self, "_og_source"):
            self._og_source, _ = ArticleImageSource.objects.get_or_create(
                slug="og-image", defaults={"name": "OG Image"},
            )
        return self._og_source

    def extract_new(self, batch_size: int = 0) -> tuple[int, int, int, list[str]]:
        """Extract content for articles not yet fetched.

        Only processes articles from the last self.days days (or with no date).
        Uses domain-based scheduling to avoid hammering any single host.

        Returns (total, extracted, fallback_count, errors).
        """
        cutoff = django_tz.now() - timedelta(days=self.days)
        qs = (
            Article.objects.filter(pipeline__content_extracted_at__isnull=True)
            .filter(Q(published__gte=cutoff) | Q(published__isnull=True))
            .exclude(url="")
            .order_by("?")
            .values_list("id", "url", "rss_content")
        )
        if batch_size:
            qs = qs[:batch_size]
        articles = list(qs)

        if not articles:
            self._write("No articles to extract.\n")
            return 0, 0, 0, []

        self._write(f"Extracting content for {len(articles)} articles...\n")

        # Group articles by domain
        domain_queues: dict[str, deque] = defaultdict(deque)
        rss_lookup: dict[int, str] = {}
        for aid, url, rss_content in articles:
            domain = get_domain(url)
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
        in_flight: dict = {}  # future -> (aid, domain)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while domain_queues or in_flight:
                # Submit new tasks for domains we can acquire
                random.shuffle(domains)
                for domain in domains:
                    if len(in_flight) >= self.workers:
                        break
                    if domain not in domain_queues:
                        continue
                    if not acquire_domain(domain):
                        continue
                    aid, url = domain_queues[domain].popleft()
                    if not domain_queues[domain]:
                        del domain_queues[domain]
                    future = pool.submit(fetch_and_extract, aid, url)
                    in_flight[future] = (aid, domain)

                # Collect finished results (non-blocking)
                finished = [f for f in in_flight if f.done()]
                for future in finished:
                    aid, domain = in_flight.pop(future)
                    release_domain(domain)

                    article_id, clean_text, og_image, content_images, err_category, err_message = future.result()
                    rss_content = rss_lookup.get(article_id, "")
                    done_count += 1

                    # Create ArticleImage for discovered image URLs
                    # Use og:image first; fall back to content images only if no sources exist
                    if og_image:
                        ArticleImage.objects.get_or_create(
                            article_id=article_id,
                            source_url=og_image[:2000],
                            defaults={"source": self._get_og_source()},
                        )

                    if not ArticleImage.objects.filter(article_id=article_id).exists():
                        for img_url in content_images:
                            ArticleImage.objects.get_or_create(
                                article_id=article_id,
                                source_url=img_url[:2000],
                            )

                    # Determine content and error fields
                    if err_category:
                        use_fallback = rss_content and len(rss_content) >= 50
                        if use_fallback:
                            content = _html_to_markdown(rss_content)
                            error_msg = f"[{err_category}] {err_message} (rss fallback)"[:500]
                            extracted += 1
                            fallback_count += 1
                        else:
                            content = ""
                            error_msg = f"[{err_category}] {err_message}"[:500]
                            errors.append(f"[{err_category}] {err_message}")
                            error_counts[err_category] += 1

                        Article.objects.filter(id=article_id).update(content=content)
                    else:
                        Article.objects.filter(id=article_id).update(content=clean_text)
                        extracted += 1

                    ArticlePipeline.objects.update_or_create(
                        article_id=article_id,
                        defaults={"content_extracted_at": django_tz.now()},
                    )

                    if done_count % 100 == 0:
                        self._write(
                            f"  {done_count}/{len(articles)} processed "
                            f"({extracted} ok, {len(errors)} failed)\n"
                        )

                # If nothing finished, sleep briefly to avoid busy-waiting
                if not finished:
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

        return len(articles), extracted, fallback_count, errors
