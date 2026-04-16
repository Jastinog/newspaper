import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.harvester.retention import ARTICLE_RETENTION_DAYS

logger = logging.getLogger(__name__)


@shared_task(name="harvester.cleanup")
def cleanup_articles():
    """Delete articles older than retention window that are not linked to any digest."""
    from apps.feed.models import Article

    cutoff = timezone.now() - timedelta(days=ARTICLE_RETENTION_DAYS)
    deleted_articles, _ = (
        Article.objects
        .filter(published__lt=cutoff)
        .exclude(digest_items__isnull=False)
        .delete()
    )

    logger.info("Cleanup done: %d articles deleted", deleted_articles)
    return {"deleted_articles": deleted_articles}
