from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.digest.models import Digest, DigestItem
from apps.feed.models import Article, Category
from apps.research.models import Research


class StaticSitemap(Sitemap):
    priority = 1.0
    changefreq = "hourly"

    def items(self):
        return ["index", "feeds_list", "articles_list"]

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        if item == "index":
            digest = Digest.objects.order_by("-created_at").only("created_at").first()
            return digest.created_at if digest else None
        return None


class DigestSitemap(Sitemap):
    priority = 0.9
    changefreq = "daily"

    def items(self):
        return (
            Digest.objects
            .order_by("-date")
            .only("date", "created_at")
        )

    def location(self, obj):
        return reverse("digest_by_date", kwargs={"date": obj.date.isoformat()})

    def lastmod(self, obj):
        return obj.created_at


class StorySitemap(Sitemap):
    limit = 5000
    priority = 0.8
    changefreq = "never"

    def items(self):
        return (
            DigestItem.objects
            .order_by("-digest__date", "-importance")
            .only("id", "digest__date")
        )

    def location(self, obj):
        return reverse("story_detail", kwargs={"item_id": obj.pk})

    def lastmod(self, obj):
        return obj.digest.date


class CategorySitemap(Sitemap):
    priority = 0.7
    changefreq = "daily"

    def items(self):
        return Category.objects.all()

    def lastmod(self, obj):
        latest = (
            Article.objects
            .filter(feed__category=obj, published__isnull=False)
            .order_by("-published")
            .only("published")
            .first()
        )
        return latest.published if latest else None


class ResearchSitemap(Sitemap):
    priority = 0.6
    changefreq = "never"

    def items(self):
        return Research.objects.order_by("-created_at").only("item_id", "created_at")

    def location(self, obj):
        return reverse("research", kwargs={"item_id": obj.item_id})

    def lastmod(self, obj):
        return obj.created_at


class ArticleSitemap(Sitemap):
    limit = 5000
    priority = 0.5
    changefreq = "monthly"

    def items(self):
        return (
            Article.objects
            .filter(published__isnull=False)
            .exclude(slug="")
            .order_by("-published")
            .only("pk", "slug", "published")
        )

    def lastmod(self, obj):
        return obj.published


sitemaps = {
    "static": StaticSitemap,
    "digests": DigestSitemap,
    "stories": StorySitemap,
    "categories": CategorySitemap,
    "research": ResearchSitemap,
    "articles": ArticleSitemap,
}
