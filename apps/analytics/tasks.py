import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

ANALYTICS_RETENTION_HOURS = 24


@shared_task(name="analytics.cleanup")
def cleanup_analytics():
    """Delete analytics data older than 24 hours."""
    from apps.analytics.models import Activity, Client, Session

    cutoff = timezone.now() - timedelta(hours=ANALYTICS_RETENTION_HOURS)

    # Activities cascade from Session, but bulk-deleting them first is cheaper
    # than relying on per-row CASCADE.
    act_deleted, _ = Activity.objects.filter(timestamp__lt=cutoff).delete()
    sess_deleted, _ = Session.objects.filter(started_at__lt=cutoff).delete()
    client_deleted, _ = Client.objects.filter(sessions__isnull=True).delete()

    logger.info(
        "Analytics cleanup: %d activities, %d sessions, %d clients deleted",
        act_deleted, sess_deleted, client_deleted,
    )
    return {
        "activities": act_deleted,
        "sessions": sess_deleted,
        "clients": client_deleted,
    }
