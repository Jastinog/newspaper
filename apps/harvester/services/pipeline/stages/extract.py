import logging

from django.db.models import F, Q

from apps.feed.models import Article
from apps.harvester.models import STAGE_EXTRACT
from ...extraction import ContentExtractor
from ...http import Domain
from ...images import ImagePicker
from .base import PipelineStage

logger = logging.getLogger(__name__)


class ExtractStage(PipelineStage):
    """Extract full article content from the source page, batched."""

    stage = STAGE_EXTRACT
    enable_field = "enable_content_extraction"
    BATCH = 30

    def candidates(self):
        return list(
            Article.objects
            .filter(status=Article.Status.PENDING)
            .filter(Q(published__gte=self.cutoff_days()) | Q(published__isnull=True))
            .exclude(url="")
            .values_list("id", "url", "image_url")
            .order_by(F("published").desc(nulls_last=True))[:self.BATCH]
        )

    def lock_domain(self, row):
        _aid, url, _image_url = row
        return Domain.of(url)

    def handle(self, row, domain):
        aid, url, current_image_url = row
        result = ContentExtractor.extract(aid, url)

        updates: dict = {"status": Article.Status.EXTRACTED}
        if result.content:
            updates["content"] = result.content
        if not current_image_url:
            picked = ImagePicker.from_extraction(result.og_image, result.content_images)
            if picked:
                updates["image_url"] = picked[:2000]

        Article.objects.filter(id=aid).update(**updates)
        logger.info("Extracted article %s from %s", aid, domain)
