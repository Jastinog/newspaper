import logging

from django.db.models import F

from apps.feed.models import Article
from apps.harvester.models import STAGE_DOWNLOAD
from ...http import Domain
from ...images import ImageDownloader
from .base import PipelineStage

logger = logging.getLogger(__name__)


class DownloadStage(PipelineStage):
    """Highest priority: download images for extracted articles, then complete
    them. An article whose image can't be downloaded is dropped, not stored —
    the feed is image-led, so an image-less card is junk."""

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
        downloaded = bool(image_url) and ImageDownloader.download_to_article(article_id, image_url)
        if not downloaded:
            Article.objects.filter(id=article_id).delete()
            logger.info("Dropped article %s: no image", article_id)
            return
        Article.objects.filter(id=article_id).update(status=Article.Status.COMPLETED)
        logger.info("Completed article %s", article_id)
