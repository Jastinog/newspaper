import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html import unescape

import feedparser
import requests
from django.db import IntegrityError
from django.utils import timezone as django_tz

from apps.harvester.models import HarvesterFeed, RunStatus
from apps.feed.models import Article, ArticleImage, Feed
from .http import random_headers

logger = logging.getLogger(__name__)

TIMEOUT = 15
MAX_WORKERS = 20


def _extract_rss_image(entry) -> str:
    """Extract the best image URL from a feedparser entry."""
    # 1. media:content or media:thumbnail
    for attr in ("media_content", "media_thumbnail"):
        media = getattr(entry, attr, None)
        if media and isinstance(media, list):
            for m in media:
                url = m.get("url", "")
                if url:
                    return url

    # 2. <enclosure> with image type
    image_extensions = (".jpg", ".jpeg", ".png", ".webp")
    for enc in getattr(entry, "enclosures", []):
        enc_type = enc.get("type", "")
        url = enc.get("href", "") or enc.get("url", "")
        if not url:
            continue
        if "image" in enc_type or url.lower().endswith(image_extensions):
            return url

    # 3. First <img> in RSS summary/description HTML
    for field in ("summary", "description", "content"):
        val = getattr(entry, field, None)
        if isinstance(val, list):
            val = val[0].get("value", "") if val else ""
        if val:
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', str(val), re.IGNORECASE)
            if match:
                return match.group(1)

    return ""


def _strip_html_basic(text: str) -> str:
    """Strip HTML tags and decode entities from RSS content."""
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_single_feed(feed_id, url, title):
    """Fetch and parse a single RSS feed. Runs in a thread."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=random_headers())
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        return feed_id, parsed.entries, None
    except Exception as e:
        return feed_id, [], f"{title}: {e}"


def _save_articles(feed_id, entries) -> tuple[int, list[int]]:
    """Save articles from parsed RSS entries. Returns (count, article_ids)."""
    new_count = 0
    article_ids = []
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
                    published = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
                break

        # Grab RSS description/summary as fallback content
        rss_content = ""
        for field in ("summary", "description", "content"):
            val = getattr(entry, field, None)
            if isinstance(val, list):
                val = val[0].get("value", "") if val else ""
            if val:
                rss_content = _strip_html_basic(str(val)).strip()
                break

        # Skip articles older than 30 days
        if published and published < datetime.now(timezone.utc) - timedelta(days=30):
            continue

        image_url = _extract_rss_image(entry)

        try:
            article = Article.objects.create(
                feed_id=feed_id,
                title=title[:1000],
                url=link[:2000],
                published=published,
                rss_content=rss_content,
            )
            new_count += 1
            article_ids.append(article.id)
            if image_url:
                ArticleImage.objects.create(
                    article=article,
                    source_url=image_url[:2000],
                    is_primary=True,
                )
        except IntegrityError:
            pass

    return new_count, article_ids


class FeedFetcher:
    """Fetch articles from RSS feeds."""

    def __init__(self, workers: int = MAX_WORKERS, stdout=None):
        self.workers = workers
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def fetch_feeds(self, feeds: list[Feed]) -> list[HarvesterFeed]:
        """Fetch specific feeds. Creates HarvesterFeed record for each.

        Returns list of HarvesterFeed objects.
        """
        if not feeds:
            return []

        self._write(f"Fetching {len(feeds)} feeds...\n")
        runs = []

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_fetch_single_feed, f.id, f.url, f.title): f
                for f in feeds
            }

            for future in as_completed(futures):
                feed = futures[future]
                feed_id, entries, error = future.result()
                now = django_tz.now()

                if error:
                    run = HarvesterFeed.objects.create(
                        feed=feed,
                        finished_at=now,
                        status=RunStatus.ERROR,
                        error_message=error,
                    )
                else:
                    new_count, article_ids = _save_articles(feed_id, entries)
                    run = HarvesterFeed.objects.create(
                        feed=feed,
                        finished_at=now,
                        status=RunStatus.SUCCESS,
                        new_articles=new_count,
                    )
                    if article_ids:
                        run.articles.add(*article_ids)

                runs.append(run)
                feed.last_fetched = now
                feed.save(update_fields=["last_fetched"])

        total_new = sum(c.new_articles for c in runs)
        self._write(f"Done: {total_new} new articles from {len(feeds)} feeds\n")
        return runs

    def fetch_all(self) -> tuple[int, int, list[str]]:
        """Fetch all enabled feeds. Returns (feeds_count, new_articles, errors).

        Legacy interface — delegates to fetch_feeds().
        """
        feeds = list(Feed.objects.filter(enabled=True))
        if not feeds:
            return 0, 0, []

        runs = self.fetch_feeds(feeds)

        total_new = sum(c.new_articles for c in runs)
        errors = [c.error_message for c in runs if c.status == RunStatus.ERROR]
        return len(feeds), total_new, errors
