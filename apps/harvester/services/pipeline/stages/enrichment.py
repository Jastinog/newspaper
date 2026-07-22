import logging
import time

from django.db.models import F

from apps.feed.models import Article
from .base import PipelineStage

logger = logging.getLogger(__name__)


class EnrichmentStage(PipelineStage):
    """Best-effort enrichment pass over COMPLETED articles.

    Enrichment runs *off* the terminal status — it flags completed articles via
    a boolean field (`flag_field`) rather than gating their completion — so
    every candidate already cleared the earlier quality gates (image + enough
    text) and disabling the stage never strands an article mid-pipeline. It uses
    a local model or a remote inference service, and is best-effort: when the
    model proves unavailable the stage backs off for `DEGRADED_COOLDOWN_SEC` and
    leaves those articles *unflagged*, then retries automatically once the
    cooldown expires. A transient outage (e.g. a cold-start HTTP timeout) thus
    self-heals within the same process instead of stalling enrichment until the
    daemon happens to restart, while a genuinely-down model isn't hammered.
    During the cooldown the stage reports idle (no candidates) so it neither
    burns CPU nor floods the pipeline-event timeline with phantom no-ops.

    Subclasses set `stage`, `enable_field`, `flag_field`, `verb`, and implement
    `enrich(article_id, title, content) -> int` (the returned count is logged).
    """

    flag_field: str = ""
    verb: str = "Enriched"
    BATCH = 20
    # How long to back off after the model/service fails before retrying it.
    DEGRADED_COOLDOWN_SEC = 300

    def __init__(self):
        # Monotonic instant until which the model is treated as unavailable;
        # 0 means healthy. Set on failure, expires on its own — no restart needed.
        self._degraded_until = 0.0

    def enrich(self, article_id: int, title: str, content: str) -> int:
        raise NotImplementedError

    def candidates(self):
        # Backing off after a recent failure — report idle so the manager stops
        # ticking us until the cooldown expires (avoids a tight no-op loop).
        if time.monotonic() < self._degraded_until:
            return []
        return list(
            Article.objects
            .filter(status=Article.Status.COMPLETED, **{self.flag_field: False})
            .filter(published__gte=self.cutoff_days())
            .values_list("id", "title", "content")
            .order_by(F("published").desc(nulls_last=True))[:self.BATCH]
        )

    def lock_domain(self, row):
        return None  # local CPU work, nothing to rate-limit

    def handle(self, row, domain):
        aid, title, content = row

        # Guard against a failure mid-batch: once the model trips the cooldown we
        # skip the rest of this batch too, leaving those articles unflagged.
        if time.monotonic() < self._degraded_until:
            return

        try:
            n = self.enrich(aid, title or "", content or "")
            logger.info("%s article %s → %d", self.verb, aid, n)
        except Exception:
            # Transient/unavailable model: back off and keep the article
            # unflagged for retry once the cooldown expires.
            self._degraded_until = time.monotonic() + self.DEGRADED_COOLDOWN_SEC
            logger.exception(
                "%s model unavailable; backing off %ds before retry",
                self.verb, self.DEGRADED_COOLDOWN_SEC,
            )
            return

        Article.objects.filter(id=aid).update(**{self.flag_field: True})
