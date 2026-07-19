from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from apps.harvester.models import DomainThrottle


class DomainLock:
    """Global per-domain rate limiting shared across all pipeline stages."""

    DOMAIN_DELAY = 10.0  # seconds between requests to the same domain
    LOCK_TIMEOUT = 60.0  # seconds before a lock is considered stale

    @classmethod
    def acquire(cls, domain: str, delay: float = DOMAIN_DELAY) -> bool:
        """Atomically try to lock a domain for a request.

        Returns True if acquired. The caller MUST call release() after the
        request completes (success or failure).
        """
        now = timezone.now()
        cutoff = now - timedelta(seconds=delay)
        stale = now - timedelta(seconds=cls.LOCK_TIMEOUT)

        # Try to acquire an existing, unlocked, ready domain.
        updated = DomainThrottle.objects.filter(
            domain=domain,
            last_request_at__lte=cutoff,
        ).filter(
            Q(locked_at__isnull=True) | Q(locked_at__lte=stale),
        ).update(locked_at=now)

        if updated:
            return True

        # If no record exists yet, create it locked.
        if not DomainThrottle.objects.filter(domain=domain).exists():
            try:
                DomainThrottle.objects.create(domain=domain, locked_at=now)
                return True
            except IntegrityError:
                return False

        return False

    @classmethod
    def release(cls, domain: str) -> None:
        """Mark a domain request as complete: update last_request_at and unlock."""
        DomainThrottle.objects.filter(domain=domain).update(
            last_request_at=timezone.now(),
            locked_at=None,
        )
