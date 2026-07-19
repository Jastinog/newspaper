import logging

from django.db.models import F

from apps.feed.models import Article
from apps.harvester.models import STAGE_DOWNLOAD
from ...http import Domain
from ...images import ImageDownloader
from .base import PipelineStage

logger = logging.getLogger(__name__)


class DownloadStage(PipelineStage):
    """Highest priority: download images for extracted articles, then complete them."""

    stage = STAGE_DOWNLOAD
    enable_field = "enable_image_download"
    BATCH = 30

    def candidates(self):
        return list(
            Article.objects.filter(
                status=Article.Status.EXTRACTED,
                published__gte=self.cutoff_days(),
            )
            .values_list("id", "image_url")
            .order_by(F("published").desc(nulls_last=True))[:self.BATCH]
        )

    def lock_domain(self, row):
        _article_id, image_url = row
        return Domain.of(image_url) if image_url else None

    def handle(self, row, domain):
        article_id, image_url = row
        if image_url:
            ImageDownloader.download_to_article(article_id, image_url)
        Article.objects.filter(id=article_id).update(status=Article.Status.COMPLETED)
        logger.info("Completed article %s", article_id)
