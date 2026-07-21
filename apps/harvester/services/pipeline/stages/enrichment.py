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
    model proves unloadable this process stops retrying it and flags articles
    done untouched, so the pass never stalls behind a broken model.

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

        if not self._degraded:
            try:
                n = self.enrich(aid, title or "", content or "")
                logger.info("%s article %s → %d", self.verb, aid, n)
            except Exception:
                self._degraded = True
                logger.exception(
                    "%s model unavailable; flagging articles done untouched", self.verb
                )

        Article.objects.filter(id=aid).update(**{self.flag_field: True})
