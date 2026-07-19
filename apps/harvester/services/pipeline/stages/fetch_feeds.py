import logging
from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from apps.feed.models import Feed
from apps.harvester.models import HarvesterFeed, RunStatus, STAGE_FEED
from ...feeds import ArticleSaver, FeedFetcher
from ...http import Domain
from .base import PipelineStage

logger = logging.getLogger(__name__)


class FetchFeedsStage(PipelineStage):
    """Lowest priority: fetch a batch of due feeds and store new articles."""

    stage = STAGE_FEED
    enable_field = "enable_feed_fetching"
    BATCH = 50
    INTERVAL_MINUTES = 10

    def candidates(self):
        cutoff = timezone.now() - timedelta(minutes=self.INTERVAL_MINUTES)
        return list(
            Feed.objects
            .filter(enabled=True)
            .filter(Q(last_fetched__lt=cutoff) | Q(last_fetched__isnull=True))
            .values_list("id", "url", "title")
            .order_by(F("last_fetched").asc(nulls_first=True))[:self.BATCH]
        )

    def lock_domain(self, row):
        _feed_id, url, _title = row
        return Domain.of(url)

    def handle(self, row, domain):
        feed_id, url, title = row
        _fid, entries, error = FeedFetcher.fetch_one(feed_id, url, title)
        now = timezone.now()

        if error:
            HarvesterFeed.objects.create(
                feed_id=feed_id, finished_at=now,
                status=RunStatus.ERROR, error_message=error,
            )
            logger.warning("Feed %s error: %s", title, error)
        else:
            new_count, article_ids = ArticleSaver.save(feed_id, entries)
            run = HarvesterFeed.objects.create(
                feed_id=feed_id, finished_at=now,
                status=RunStatus.SUCCESS, new_articles=new_count,
            )
            if article_ids:
                run.articles.add(*article_ids)
            logger.info("Feed %s: %d new articles", title, new_count)

        Feed.objects.filter(id=feed_id).update(last_fetched=now)
