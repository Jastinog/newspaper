import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import NamedTuple

import feedparser
import requests
from django.db import transaction
from django.db.models.functions import Greatest
from django.utils import timezone as django_tz
from django.utils.text import slugify

from apps.harvester.models import HarvesterFeed, RunStatus
from apps.harvester.retention import ARTICLE_RETENTION_DAYS
from apps.feed.models import Article, ArticleImage, ArticleImageSource, ArticlePipeline, Feed
from .http import get_domain, random_headers
from .throttle import acquire_domain, release_domain

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


def fetch_single_feed(feed_id, url, title):
    """Fetch and parse a single RSS feed. Runs in a thread."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=random_headers())
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        return feed_id, parsed.entries, None
    except Exception as e:
        return feed_id, [], f"{title}: {e}"


def _get_rss_source():
    src, _ = ArticleImageSource.objects.get_or_create(slug="rss-image", defaults={"name": "RSS Image"})
    return src


def _parse_published(entry):
    """Extract a timezone-aware datetime from a feedparser entry, or None."""
    for date_field in ("published_parsed", "updated_parsed"):
        parsed_time = getattr(entry, date_field, None)
        if parsed_time:
            try:
                return datetime(*parsed_time[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def _extract_rss_content(entry) -> str:
    """Grab RSS description/summary as fallback article content."""
    for field in ("summary", "description", "content"):
        val = getattr(entry, field, None)
        if isinstance(val, list):
            val = val[0].get("value", "") if val else ""
        if val:
            return _strip_html_basic(str(val)).strip()
    return ""


class _Candidate(NamedTuple):
    url: str
    title: str
    published: datetime
    rss_content: str
    image_url: str


def save_articles(feed_id, entries) -> tuple[int, list[int]]:
    """Save new articles from parsed RSS entries. Returns (count, article_ids).

    Dedup strategy:
      1. In-memory filter: drop entries without `published`, older than HWM,
         or outside the retention window. If nothing survives, 0 DB calls.
      2. Bulk SELECT of surviving URLs to filter out already-stored articles.
      3. Bulk INSERT with ignore_conflicts=True as a race-condition safety net.
      4. Advance the feed's HWM to max(entry.published) so the next poll can
         short-circuit even faster.
    """
    if not entries:
        return 0, []

    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=ARTICLE_RETENTION_DAYS)
    hwm = (
        Feed.objects.only("last_entry_published")
        .get(pk=feed_id).last_entry_published
    )

    # 1. In-memory filter. Extract everything we need from `entry` here so
    # the parsed RSS payload can be GC'd before we hit the DB.
    candidates: list[_Candidate] = []
    max_entry_pub = None
    for entry in entries:
        link = (getattr(entry, "link", "") or "").strip()
        if not link:
            continue
        published = _parse_published(entry)
        if not published:
            continue
        if max_entry_pub is None or published > max_entry_pub:
            max_entry_pub = published
        if hwm is not None and published <= hwm:
            continue
        if published < retention_cutoff:
            continue
        candidates.append(_Candidate(
            url=link[:2000],
            title=(getattr(entry, "title", "") or "")[:1000],
            published=published,
            rss_content=_extract_rss_content(entry),
            image_url=_extract_rss_image(entry),
        ))

    # Advance HWM via Greatest() so concurrent writers can't rewind it.
    if max_entry_pub is not None and (hwm is None or max_entry_pub > hwm):
        Feed.objects.filter(pk=feed_id).update(
            last_entry_published=Greatest("last_entry_published", max_entry_pub),
        )

    if not candidates:
        return 0, []

    # 2. Bulk dedup via one SELECT
    candidate_urls = [c.url for c in candidates]
    existing_urls = set(
        Article.objects.filter(url__in=candidate_urls).values_list("url", flat=True)
    )
    to_insert = [c for c in candidates if c.url not in existing_urls]
    if not to_insert:
        return 0, []

    # 3. Bulk INSERT with safety net for races. bulk_create bypasses
    # Article.save(), so populate the slug explicitly here.
    rss_source = _get_rss_source()
    articles = [
        Article(
            feed_id=feed_id,
            title=c.title,
            slug=slugify(c.title, allow_unicode=True)[:300],
            url=c.url,
            published=c.published,
            rss_content=c.rss_content,
        )
        for c in to_insert
    ]
    with transaction.atomic():
        Article.objects.bulk_create(articles, ignore_conflicts=True)
        # ignore_conflicts on PG doesn't populate pks, so reload by URL.
        by_url = dict(
            Article.objects.filter(url__in=candidate_urls)
            .values_list("url", "id")
        )
        ArticlePipeline.objects.bulk_create(
            [ArticlePipeline(article_id=aid) for aid in by_url.values()],
            ignore_conflicts=True,
        )
        image_rows = [
            ArticleImage(
                article_id=by_url[c.url],
                source=rss_source,
                source_url=c.image_url[:2000],
                is_primary=True,
            )
            for c in to_insert
            if c.image_url and c.url in by_url
        ]
        if image_rows:
            ArticleImage.objects.bulk_create(image_rows, ignore_conflicts=True)

    article_ids = [by_url[c.url] for c in to_insert if c.url in by_url]
    return len(article_ids), article_ids


class FeedFetcher:
    """Fetch articles from RSS feeds."""

    def __init__(self, workers: int = MAX_WORKERS, stdout=None):
        self.workers = workers
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def fetch_feeds(self, feeds: list[Feed]) -> list[HarvesterFeed]:
        """Fetch specific feeds with per-domain throttling.

        Returns list of HarvesterFeed objects.
        """
        if not feeds:
            return []

        self._write(f"Fetching {len(feeds)} feeds...\n")
        runs = []

        # Build domain queues
        feed_queue: list[Feed] = list(feeds)
        random.shuffle(feed_queue)
        domain_feeds: dict[str, list[Feed]] = {}
        for f in feed_queue:
            domain = get_domain(f.url)
            domain_feeds.setdefault(domain, []).append(f)

        domains = list(domain_feeds.keys())
        in_flight: dict = {}  # future -> (Feed, domain)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while domain_feeds or in_flight:
                # Submit new tasks for domains we can acquire
                random.shuffle(domains)
                for domain in domains:
                    if len(in_flight) >= self.workers:
                        break
                    if domain not in domain_feeds:
                        continue
                    if not acquire_domain(domain):
                        continue
                    feed = domain_feeds[domain].pop(0)
                    if not domain_feeds[domain]:
                        del domain_feeds[domain]
                    future = pool.submit(fetch_single_feed, feed.id, feed.url, feed.title)
                    in_flight[future] = (feed, domain)

                # Collect finished results (non-blocking)
                finished = [f for f in in_flight if f.done()]
                for future in finished:
                    feed, domain = in_flight.pop(future)
                    release_domain(domain)

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
                        new_count, article_ids = save_articles(feed_id, entries)
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

                if not finished:
                    time.sleep(0.1)

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
