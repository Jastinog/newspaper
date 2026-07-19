import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests
from django.utils import timezone as django_tz

from apps.feed.models import Feed
from apps.harvester.models import HarvesterFeed, RunStatus
from ..http import BrowserHeaders, Domain
from ..throttle import DomainLock
from .saver import ArticleSaver

logger = logging.getLogger(__name__)


class FeedFetcher:
    """Fetch articles from RSS feeds concurrently, one request per domain at a time."""

    TIMEOUT = 15
    MAX_WORKERS = 20

    def __init__(self, workers: int = MAX_WORKERS, stdout=None):
        self.workers = workers
        self.stdout = stdout

    @classmethod
    def fetch_one(cls, feed_id, url, title) -> tuple[int, list, str | None]:
        """Download and parse a single feed. Returns (feed_id, entries, error)."""
        try:
            resp = requests.get(url, timeout=cls.TIMEOUT, headers=BrowserHeaders.random())
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            return feed_id, parsed.entries, None
        except Exception as e:
            return feed_id, [], f"{title}: {e}"

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
            domain = Domain.of(f.url)
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
                    if not DomainLock.acquire(domain):
                        continue
                    feed = domain_feeds[domain].pop(0)
                    if not domain_feeds[domain]:
                        del domain_feeds[domain]
                    future = pool.submit(self.fetch_one, feed.id, feed.url, feed.title)
                    in_flight[future] = (feed, domain)

                finished = [f for f in in_flight if f.done()]
                for future in finished:
                    feed, domain = in_flight.pop(future)
                    DomainLock.release(domain)

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
                        new_count, article_ids = ArticleSaver.save(feed_id, entries)
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
