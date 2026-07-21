from apps.feed.services.classify import classify_article
from apps.harvester.models import STAGE_CLASSIFY
from .enrichment import EnrichmentStage


class ClassifyStage(EnrichmentStage):
    """Assign content topics to completed articles (local ONNX zero-shot model)."""

    stage = STAGE_CLASSIFY
    enable_field = "enable_topic_classification"
    flag_field = "classified"
    verb = "Classified"

    def enrich(self, article_id, title, content):
        return classify_article(article_id, title, content)
