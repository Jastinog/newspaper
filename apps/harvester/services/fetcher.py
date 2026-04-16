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

from apps.feed.models import Article, Feed
from apps.harvester.models import HarvesterFeed, RunStatus
from apps.harvester.retention import ARTICLE_RETENTION_DAYS
from .http import get_domain, random_headers
from .image_picker import pick_from_rss_entry
from .throttle import acquire_domain, release_domain

logger = logging.getLogger(__name__)

TIMEOUT = 15
MAX_WORKERS = 20


def _strip_html_basic(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_single_feed(feed_id, url, title):
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=random_headers())
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        return feed_id, parsed.entries, None
    except Exception as e:
        return feed_id, [], f"{title}: {e}"


def _parse_published(entry):
    for date_field in ("published_parsed", "updated_parsed"):
        parsed_time = getattr(entry, date_field, None)
        if parsed_time:
            try:
                return datetime(*parsed_time[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def _extract_entry_text(entry) -> str:
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
    content: str
    image_url: str


def save_articles(feed_id, entries) -> tuple[int, list[int]]:
    """Save new articles from parsed RSS entries. Returns (count, article_ids)."""
    if not entries:
        return 0, []

    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=ARTICLE_RETENTION_DAYS)
    hwm = (
        Feed.objects.only("last_entry_published")
        .get(pk=feed_id).last_entry_published
    )

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
            content=_extract_entry_text(entry),
            image_url=pick_from_rss_entry(entry)[:2000],
        ))

    if max_entry_pub is not None and (hwm is None or max_entry_pub > hwm):
        Feed.objects.filter(pk=feed_id).update(
            last_entry_published=Greatest("last_entry_published", max_entry_pub),
        )

    if not candidates:
        return 0, []

    candidate_urls = [c.url for c in candidates]
    existing_urls = set(
        Article.objects.filter(url__in=candidate_urls).values_list("url", flat=True)
    )
    to_insert = [c for c in candidates if c.url not in existing_urls]
    if not to_insert:
        return 0, []

    articles = [
        Article(
            feed_id=feed_id,
            title=c.title,
            slug=slugify(c.title, allow_unicode=True)[:300],
            url=c.url,
            published=c.published,
            content=c.content,
            image_url=c.image_url,
            status=Article.Status.PENDING,
        )
        for c in to_insert
    ]
    with transaction.atomic():
        Article.objects.bulk_create(articles, ignore_conflicts=True)
        by_url = dict(
            Article.objects.filter(url__in=candidate_urls)
            .values_list("url", "id")
        )

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
        if not feeds:
            return []

        self._write(f"Fetching {len(feeds)} feeds...\n")
        runs = []

        feed_queue: list[Feed] = list(feeds)
        random.shuffle(feed_queue)
        domain_feeds: dict[str, list[Feed]] = {}
        for f in feed_queue:
            domain = get_domain(f.url)
            domain_feeds.setdefault(domain, []).append(f)

        domains = list(domain_feeds.keys())
        in_flight: dict = {}

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while domain_feeds or in_flight:
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
        feeds = list(Feed.objects.filter(enabled=True))
        if not feeds:
            return 0, 0, []

        runs = self.fetch_feeds(feeds)

        total_new = sum(c.new_articles for c in runs)
        errors = [c.error_message for c in runs if c.status == RunStatus.ERROR]
        return len(feeds), total_new, errors
