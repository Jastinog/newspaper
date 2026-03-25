from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.feed.models import ArticleImage


class Command(BaseCommand):
    help = "Backfill is_primary for articles with a single downloaded image"

    def handle(self, *args, **options):
        # Articles with exactly one successfully downloaded image
        article_ids = (
            ArticleImage.objects
            .filter(downloaded=True)
            .exclude(image="")
            .values("article_id")
            .annotate(cnt=Count("id"))
            .filter(cnt=1)
            .values_list("article_id", flat=True)
        )

        updated = ArticleImage.objects.filter(
            article_id__in=list(article_ids),
            downloaded=True,
            is_primary=False,
        ).exclude(image="").update(is_primary=True)

        self.stdout.write(f"Updated {updated} images to is_primary=True")
