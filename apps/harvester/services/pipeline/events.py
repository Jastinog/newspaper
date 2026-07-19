import logging
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

from apps.harvester.models import PipelineEvent

logger = logging.getLogger(__name__)


class PipelineEventRecorder:
    """Persist pipeline stage executions for timeline visualization."""

    RETENTION_HOURS = 1

    @staticmethod
    def record(stage, started_at, success, article_id=None) -> None:
        finished_at = timezone.now()
        duration_ms = max(1, int((finished_at - started_at).total_seconds() * 1000))
        try:
            PipelineEvent.objects.create(
                stage=stage, started_at=started_at, finished_at=finished_at,
                duration_ms=duration_ms, success=success, article_id=article_id,
            )
        except Exception:
            logger.debug("Failed to record pipeline event", exc_info=True)

    @classmethod
    def run_stage(cls, stage, fn, *args, **kwargs) -> bool:
        """Run a stage callable, recording an event on any work done or failure."""
        close_old_connections()
        started_at = timezone.now()
        try:
            result = fn(*args, **kwargs)
            if result:
                cls.record(stage, started_at, success=True)
            return result
        except Exception:
            logger.exception("Pipeline stage %s failed", getattr(fn, "__name__", stage))
            cls.record(stage, started_at, success=False)
            return False
        finally:
            close_old_connections()

    @classmethod
    def cleanup_old(cls) -> None:
        close_old_connections()
        try:
            PipelineEvent.objects.filter(
                started_at__lt=timezone.now() - timedelta(hours=cls.RETENTION_HOURS),
            ).delete()
        except Exception:
            logger.debug("Failed to clean up pipeline events", exc_info=True)
        finally:
            close_old_connections()
