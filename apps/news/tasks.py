import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="news.update")
def update_news():
    """Fetch RSS feeds, extract content, and embed articles."""
    from apps.news.services.ingest import UpdateService

    service = UpdateService()
    result = service.run()

    logger.info(
        "Update done: %d feeds, %d new articles, %d extracted, %d embedded",
        result.feeds_fetched,
        result.new_articles,
        result.articles_extracted,
        result.articles_embedded,
    )
    return {
        "feeds_fetched": result.feeds_fetched,
        "new_articles": result.new_articles,
        "articles_extracted": result.articles_extracted,
        "articles_embedded": result.articles_embedded,
    }


@shared_task(name="news.digest")
def generate_digest():
    """Generate daily digest for all languages."""
    from apps.news.services.digest import DigestService

    service = DigestService()
    digests = service.run()

    result = []
    for d in digests:
        sections = d.sections.count()
        logger.info("Digest [%s] %s: %d sections", d.language, d.date, sections)
        result.append({"language": d.language, "date": str(d.date), "sections": sections})
    return result
