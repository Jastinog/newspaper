import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="telegram.publish_next")
def publish_next_to_telegram():
    """Send the next unsent digest item to all active channels."""
    from .services import publish_next_items

    total = publish_next_items()
    logger.info("Telegram publish_next: %d items sent", total)
    return {"sent": total}
