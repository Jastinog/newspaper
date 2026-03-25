from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from apps.harvester.models import DomainThrottle

DOMAIN_DELAY = 10.0  # seconds between requests to same domain
LOCK_TIMEOUT = 60.0  # seconds before a lock is considered stale


def acquire_domain(domain: str, delay: float = DOMAIN_DELAY) -> bool:
    """Atomically try to lock a domain for a request.

    Returns True if acquired. The caller MUST call release_domain() after
    the request completes (success or failure).
    """
    now = timezone.now()
    cutoff = now - timedelta(seconds=delay)
    stale = now - timedelta(seconds=LOCK_TIMEOUT)

    # Try to acquire an existing, unlocked, ready domain
    updated = DomainThrottle.objects.filter(
        domain=domain,
        last_request_at__lte=cutoff,
    ).filter(
        Q(locked_at__isnull=True) | Q(locked_at__lte=stale),
    ).update(locked_at=now)

    if updated:
        return True

    # If no record exists yet, create it locked
    if not DomainThrottle.objects.filter(domain=domain).exists():
        try:
            DomainThrottle.objects.create(domain=domain, locked_at=now)
            return True
        except IntegrityError:
            return False

    return False


def release_domain(domain: str) -> None:
    """Mark a domain request as complete. Updates last_request_at and unlocks."""
    DomainThrottle.objects.filter(domain=domain).update(
        last_request_at=timezone.now(),
        locked_at=None,
    )
