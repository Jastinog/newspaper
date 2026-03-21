from django import template

from apps.news.models import Feed

register = template.Library()

NEUTRAL_COLOR = "#78909c"

LEAN_COLORS = {
    "left": "#1565c0",
    "center_left": "#42a5f5",
    "center": NEUTRAL_COLOR,
    "center_right": "#ef6c00",
    "right": "#c62828",
}


@register.inclusion_tag("news/_bias_spectrum.html")
def bias_spectrum(item):
    """Render a Ground News-style coverage spectrum bar for a DigestItem."""
    counts = {value: 0 for value, _ in Feed.Lean.choices}
    lean_labels = dict(Feed.Lean.choices)
    feed_map = {}
    total = 0

    for article in item.articles.select_related("feed"):
        lean = article.feed.lean
        total += 1
        if lean and lean in counts:
            counts[lean] += 1
        fid = article.feed_id
        if fid in feed_map:
            feed_map[fid]["article_count"] += 1
        else:
            feed_map[fid] = {
                "title": article.feed.title,
                "url": article.url,
                "label": lean_labels.get(lean, "Unknown"),
                "color": LEAN_COLORS.get(lean, NEUTRAL_COLOR),
                "article_count": 1,
            }

    tooltip_sources = sorted(feed_map.values(), key=lambda s: s["title"])
    has_lean_data = any(counts.values())

    if has_lean_data:
        lean_total = sum(counts.values())
        segments = [
            {
                "label": label,
                "lean": value,
                "color": LEAN_COLORS[value],
                "pct": round(count / lean_total * 100),
                "count": count,
            }
            for value, label in Feed.Lean.choices
            if (count := counts[value])
        ]
    else:
        segments = [
            {
                "label": "Neutral",
                "lean": "neutral",
                "color": NEUTRAL_COLOR,
                "pct": 100,
                "count": total,
            }
        ]

    return {
        "total": total,
        "segments": segments,
        "has_lean_data": has_lean_data,
        "tooltip_sources": tooltip_sources,
    }
