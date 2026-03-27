from django import template

register = template.Library()


@register.inclusion_tag("news/_sources.html")
def sources_panel(item):
    """Provide article-level source data for the sources modal."""
    articles = []
    for article in item.articles.all():
        primary = None
        fallback = None
        for img in article.images.all():
            if img.image:
                if img.is_primary:
                    primary = img.image.url
                    break
                if fallback is None:
                    fallback = img.image.url
        primary = primary or fallback
        articles.append({
            "title": article.title,
            "url": article.url,
            "feed_title": article.feed.title,
            "feed_website": article.feed.website or article.feed.url,
            "image_url": primary or "",
        })

    return {
        "total": len(articles),
        "source_articles": articles,
        "item_id": item.id,
    }
