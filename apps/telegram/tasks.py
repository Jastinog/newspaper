import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="telegram.publish")
def publish_digest_to_telegram():
    """Publish today's digest to all active Telegram channels."""
    from .services import publish_to_all_channels

    results = publish_to_all_channels()

    from .models import TelegramPost

    success = sum(1 for r in results if r.status == TelegramPost.Status.SUCCESS)
    failed = sum(1 for r in results if r.status == TelegramPost.Status.FAILED)
    logger.info("Telegram publish: %d success, %d failed", success, failed)

    return {"success": success, "failed": failed}
