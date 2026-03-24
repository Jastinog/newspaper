import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="crawler.update")
def update_news():
    """Fetch RSS feeds, extract content, and embed articles."""
    from apps.crawler.services import UpdateService

    service = UpdateService()
    result = service.run()

    logger.info(
        "Update done: %d feeds, %d new articles, %d extracted, %d images, %d embedded",
        result.feeds_fetched,
        result.new_articles,
        result.articles_extracted,
        result.images_downloaded,
        result.articles_embedded,
    )
    return {
        "feeds_fetched": result.feeds_fetched,
        "new_articles": result.new_articles,
        "articles_extracted": result.articles_extracted,
        "images_downloaded": result.images_downloaded,
        "articles_embedded": result.articles_embedded,
    }
