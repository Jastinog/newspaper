import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="digest.generate")
def generate_digest():
    """Generate daily digest using the Edition pipeline."""
    from apps.digest.services import EditionService

    service = EditionService()
    digest = service.run()

    item_count = digest.items.count()
    run = getattr(digest, "run", None)
    cost = float(run.total_cost_usd) if run else 0

    logger.info("Edition %s: %d items, cost=$%.4f", digest.date, item_count, cost)

    return {
        "date": str(digest.date),
        "items": item_count,
        "cost_usd": cost,
    }
