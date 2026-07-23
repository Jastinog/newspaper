from django.db.models import F

from apps.feed.models import Article
from apps.feed.services.section import assign_section
from apps.harvester.models import STAGE_SECTION
from apps.websocket.broadcast import broadcast_home_article
from .enrichment import EnrichmentStage


class SectionStage(EnrichmentStage):
    """Assign completed, embedded articles to their best DigestSection.

    Runs after EmbedStage — the match needs the article's chunk vectors — so it
    additionally requires `embedded=True` on top of the base enrichment filter.
    """

    stage = STAGE_SECTION
    enable_field = "enable_section_assignment"
    flag_field = "sectioned"
    verb = "Sectioned"

    def candidates(self):
        return list(
            Article.objects
            .filter(status=Article.Status.COMPLETED, sectioned=False, embedded=True)
            .filter(published__gte=self.cutoff_days())
            .values_list("id", "title", "content")
            .order_by(F("published").desc(nulls_last=True))[:self.BATCH]
        )

    def enrich(self, article_id, title, content):
        slug = assign_section(article_id, title, content)
        if not slug:
            return 0
        # Live-notify homepage clients that this section gained an article.
        broadcast_home_article(slug, article_id)
        return 1
