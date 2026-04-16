from datetime import timedelta
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from apps.digest.models import Digest, DigestItem

PUBLICATION_NAME = "Newspaper"

# Google News sitemaps must only include articles published in the last 2 days
NEWS_MAX_AGE_DAYS = 2


def news_sitemap(request):
    cutoff = (timezone.now() - timedelta(days=NEWS_MAX_AGE_DAYS)).date()

    digests = Digest.objects.filter(
        stage=Digest.Stage.DONE, date__gte=cutoff,
    ).values_list("pk", flat=True)

    items = (
        DigestItem.objects
        .filter(digest_id__in=digests)
        .select_related("digest")
        .prefetch_related("translations", "translations__language")
        .order_by("-digest__date", "-freshness")
    )

    pub_name = escape(PUBLICATION_NAME)
    url_entries = []

    for item in items:
        pub_date = item.digest.date.isoformat()

        for translation in item.translations.all():
            if not translation.topic:
                continue

            lang_code = translation.language.code
            loc = request.build_absolute_uri(
                f"/{lang_code}{reverse('story_detail', args=[item.pk])}"
            )

            url_entries.append(
                f"  <url>\n"
                f"    <loc>{escape(loc)}</loc>\n"
                f"    <news:news>\n"
                f"      <news:publication>\n"
                f"        <news:name>{pub_name}</news:name>\n"
                f"        <news:language>{lang_code}</news:language>\n"
                f"      </news:publication>\n"
                f"      <news:publication_date>{pub_date}</news:publication_date>\n"
                f"      <news:title>{escape(translation.topic)}</news:title>\n"
                f"    </news:news>\n"
                f"  </url>"
            )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'
        + "\n".join(url_entries)
        + "\n</urlset>\n"
    )

    return HttpResponse(xml, content_type="application/xml")
