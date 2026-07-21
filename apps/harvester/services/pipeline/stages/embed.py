from apps.feed.services.embed import embed_article
from apps.harvester.models import STAGE_EMBED
from .enrichment import EnrichmentStage


class EmbedStage(EnrichmentStage):
    """Chunk + embed completed articles with the local ONNX model for semantic search."""

    stage = STAGE_EMBED
    enable_field = "enable_embedding"
    flag_field = "embedded"
    verb = "Embedded"

    def enrich(self, article_id, title, content):
        return embed_article(article_id, title, content)
