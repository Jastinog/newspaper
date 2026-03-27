from django import template

from apps.core.services.utils import get_article_image_url

register = template.Library()


@register.inclusion_tag("news/_sources.html")
def sources_panel(item):
    """Provide article-level source data for the sources modal."""
    articles = []
    for article in item.articles.all():
        articles.append({
            "title": article.title,
            "url": article.url,
            "feed_title": article.feed.title,
            "feed_website": article.feed.website or article.feed.url,
            "image_url": get_article_image_url(article),
        })

    return {
        "total": len(articles),
        "source_articles": articles,
        "item_id": item.id,
    }
