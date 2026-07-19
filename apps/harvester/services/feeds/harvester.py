from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.feed.models import Feed
from .fetcher import FeedFetcher


class FeedHarvester:
    """Select eligible feeds and harvest them in one batch."""

    INTERVAL_MINUTES = 10
    BATCH_SIZE = 20

    def __init__(self, stdout=None):
        self.fetcher = FeedFetcher(stdout=stdout)
        self.stdout = stdout

    def harvest(self):
        cutoff = timezone.now() - timedelta(minutes=self.INTERVAL_MINUTES)

        feeds = list(
            Feed.objects.filter(enabled=True)
            .filter(Q(last_fetched__isnull=True) | Q(last_fetched__lt=cutoff))
            .order_by("?")[:self.BATCH_SIZE]
        )

        if not feeds:
            return []

        return self.fetcher.fetch_feeds(feeds)
