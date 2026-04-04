import logging

from celery import shared_task
from django.test import RequestFactory

from .sitemaps import sitemaps

logger = logging.getLogger(__name__)


@shared_task(name="core.warm_sitemap_cache")
def warm_sitemap_cache():
    """Hit all sitemap URLs to populate the cache."""
    from django.contrib.sitemaps.views import index, sitemap

    factory = RequestFactory()

    # Warm the sitemap index
    request = factory.get("/sitemap.xml", SERVER_NAME="clovertube.com")
    request.META["SERVER_PORT"] = "443"
    request.META["wsgi.url_scheme"] = "https"
    index(request, sitemaps=sitemaps)
    logger.info("Sitemap index cache warmed")

    # Warm each section
    for section in sitemaps:
        page = 1
        while True:
            request = factory.get(
                f"/sitemap-{section}.xml", {"p": page},
                SERVER_NAME="clovertube.com",
            )
            request.META["SERVER_PORT"] = "443"
            request.META["wsgi.url_scheme"] = "https"
            try:
                sitemap(request, sitemaps=sitemaps, section=section)
                logger.info("Sitemap %s page %d cache warmed", section, page)
                page += 1
            except Exception:
                break  # No more pages

    logger.info("All sitemap caches warmed")
