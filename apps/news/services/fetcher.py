import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from django.db import IntegrityError

from apps.news.models import Article, Feed

logger = logging.getLogger(__name__)

TIMEOUT = 15
MAX_WORKERS = 20


def _strip_html_basic(text: str) -> str:
    """Strip HTML tags and decode entities from RSS content."""
    import re
    from html import unescape

    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_single_feed(feed_id, url, title):
    """Fetch and parse a single RSS feed. Runs in a thread."""
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        return feed_id, parsed.entries, None
    except Exception as e:
        return feed_id, [], f"{title}: {e}"


class FeedFetcher:
    """Fetch articles from all enabled RSS feeds.

    Creates Article records with title, url, and published date.
    Content is NOT saved from RSS — it will be extracted separately.
    """

    def __init__(self, workers: int = MAX_WORKERS, stdout=None):
        self.workers = workers
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def fetch_all(self) -> tuple[int, int, list[str]]:
        """Fetch all enabled feeds. Returns (feeds_count, new_articles, errors)."""
        feeds = list(Feed.objects.filter(enabled=True))
        if not feeds:
            return 0, 0, []

        self._write(f"Fetching {len(feeds)} feeds...\n")
        total_new = 0
        errors = []

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_fetch_single_feed, f.id, f.url, f.title): f
                for f in feeds
            }

            for future in as_completed(futures):
                feed = futures[future]
                feed_id, entries, error = future.result()

                if error:
                    errors.append(error)
                    continue

                new_count = 0
                for entry in entries:
                    title = getattr(entry, "title", "") or ""
                    link = getattr(entry, "link", "") or ""
                    if not link:
                        continue

                    published = None
                    for date_field in ("published_parsed", "updated_parsed"):
                        parsed_time = getattr(entry, date_field, None)
                        if parsed_time:
                            try:
                                published = datetime(
                                    *parsed_time[:6], tzinfo=timezone.utc
                                )
                            except (ValueError, TypeError):
                                pass
                            break

                    # Grab RSS description/summary as fallback content
                    rss_content = ""
                    for field in ("summary", "description", "content"):
                        val = getattr(entry, field, None)
                        if isinstance(val, list):
                            # feedparser content is a list of dicts
                            val = val[0].get("value", "") if val else ""
                        if val:
                            rss_content = _strip_html_basic(str(val)).strip()
                            break

                    # Skip articles older than 30 days
                    if published and published < datetime.now(timezone.utc) - timedelta(days=30):
                        continue

                    try:
                        Article.objects.create(
                            feed_id=feed_id,
                            title=title[:1000],
                            url=link[:2000],
                            published=published,
                            rss_content=rss_content,
                        )
                        new_count += 1
                    except IntegrityError:
                        pass

                total_new += new_count
                feed.last_fetched = datetime.now(timezone.utc)
                feed.save(update_fields=["last_fetched"])

        self._write(f"Done: {total_new} new articles from {len(feeds)} feeds\n")
        return len(feeds), total_new, errors
