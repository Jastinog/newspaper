import time
from datetime import timedelta

from django.utils import timezone

from ...throttle import DomainLock


class PipelineStage:
    """Base for a single pipeline stage.

    Subclasses set `stage` / `enable_field`, provide `candidates()` and
    `handle(row, domain)`, and implement `lock_domain(row)` to name the domain
    to rate-limit (or None to skip locking). The base owns the deadline loop,
    per-domain locking, and the "did any work" tally.

    `run()` returns True if the stage did any work (so the manager re-submits
    it promptly) or False when idle.
    """

    stage: str = ""
    enable_field: str = ""
    DAYS_LOOKBACK = 30
    DEADLINE_SEC = 30

    @classmethod
    def cutoff_days(cls):
        return timezone.now() - timedelta(days=cls.DAYS_LOOKBACK)

    def candidates(self) -> list:
        raise NotImplementedError

    def lock_domain(self, row) -> str | None:
        raise NotImplementedError

    def handle(self, row, domain) -> None:
        raise NotImplementedError

    def run(self) -> bool:
        candidates = self.candidates()
        if not candidates:
            return False

        processed = 0
        deadline = time.monotonic() + self.DEADLINE_SEC
        for row in candidates:
            if time.monotonic() > deadline:
                break

            domain = self.lock_domain(row)
            if domain is None:
                self.handle(row, None)
            else:
                if not DomainLock.acquire(domain):
                    continue
                try:
                    self.handle(row, domain)
                finally:
                    DomainLock.release(domain)
            processed += 1

        return processed > 0
