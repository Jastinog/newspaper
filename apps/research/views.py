from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from apps.digest.models import DigestItem

from .models import Research

SITE_NAME = _("Newspaper")


def research(request, item_id):
    item = get_object_or_404(
        DigestItem.objects.select_related("section__digest"), pk=item_id,
    )

    dive = Research.objects.filter(item=item).first()
    if not dive:
        return render(request, "news/research_loading.html", {"item": item})

    sources = dive.sources.select_related("article__feed").order_by("order")

    seo = {
        "title": f"{dive.title} — {SITE_NAME}",
        "description": dive.subtitle or dive.title,
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "article",
    }

    return render(request, "news/research.html", {
        "dive": dive,
        "section": item.section,
        "sources": sources,
        "seo": seo,
    })
