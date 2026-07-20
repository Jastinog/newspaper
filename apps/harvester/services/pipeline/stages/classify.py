import logging

from django.db.models import F

from apps.feed.models import Article
from apps.feed.services.classify import classify_article
from apps.harvester.models import STAGE_CLASSIFY
from .base import PipelineStage

logger = logging.getLogger(__name__)


class ClassifyStage(PipelineStage):
    """Enrichment pass: assign content topics to COMPLETED articles that haven't
    been classified yet, then flag them. Every COMPLETED article already cleared
    the earlier quality gates (image present + enough text), so no suitability
    check is needed here.

    Classification runs *off* the terminal status — it enriches completed
    articles via the `classified` flag rather than gating their completion — so
    disabling this stage never strands articles. It uses a local ONNX model (no
    HTTP, so no domain locking) and is best-effort: if the model can't run, the
    article is flagged classified untagged so the pass never stalls behind a
    broken model.
    """

    stage = STAGE_CLASSIFY
    enable_field = "enable_topic_classification"
    BATCH = 20

    def __init__(self):
        # Once the model proves unloadable, stop retrying it this process and
        # flag articles classified untagged (logged once).
        self._degraded = False

    def candidates(self):
        return list(
            Article.objects
            .filter(status=Article.Status.COMPLETED, classified=False)
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
                n = classify_article(aid, title or "", content or "")
                logger.info("Classified article %s → %d topics", aid, n)
            except Exception:
                self._degraded = True
                logger.exception(
                    "Topic classifier unavailable; flagging articles untagged"
                )

        Article.objects.filter(id=aid).update(classified=True)
