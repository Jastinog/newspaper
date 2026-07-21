import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="digest.generate")
def generate_digest():
    """Generate the daily digest by matching articles to section embeddings."""
    from apps.digest.services import EmbeddingEdition

    service = EmbeddingEdition()
    digest = service.run()

    item_count = digest.items.count()
    logger.info("Embedding edition %s: %d items", digest.date, item_count)

    return {
        "date": str(digest.date),
        "items": item_count,
    }
