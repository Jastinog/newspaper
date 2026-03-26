import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="digest.generate")
def generate_digest():
    """Generate daily digest with translations for all languages."""
    from apps.digest.services import DigestService

    service = DigestService()
    digest = service.run()

    item_count = digest.items.count()
    translation_count = digest.translations.count()
    logger.info("Digest %s: %d items, %d language(s)", digest.date, item_count, translation_count)

    return {
        "date": str(digest.date),
        "items": item_count,
        "translations": translation_count,
    }
