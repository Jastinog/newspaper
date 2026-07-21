import logging

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
    a local model (no HTTP, so no domain locking) and is best-effort: once the
    model proves unloadable this process stops retrying it for the rest of the
    run, but leaves those articles *unflagged* so a later healthy process picks
    them up — the pass never stalls, and a transient model outage self-heals
    instead of silently marking articles enriched with no output.

    Subclasses set `stage`, `enable_field`, `flag_field`, `verb`, and implement
    `enrich(article_id, title, content) -> int` (the returned count is logged).
    """

    flag_field: str = ""
    verb: str = "Enriched"
    BATCH = 20

    def __init__(self):
        self._degraded = False

    def enrich(self, article_id: int, title: str, content: str) -> int:
        raise NotImplementedError

    def candidates(self):
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

        # Model already proved unloadable this run — leave the article unflagged
        # so a later healthy process retries it, and don't touch the model again.
        if self._degraded:
            return

        try:
            n = self.enrich(aid, title or "", content or "")
            logger.info("%s article %s → %d", self.verb, aid, n)
        except Exception:
            # Transient/unloadable model: keep the article unflagged for retry.
            self._degraded = True
            logger.exception(
                "%s model unavailable; leaving articles unflagged for retry", self.verb
            )
            return

        Article.objects.filter(id=aid).update(**{self.flag_field: True})
