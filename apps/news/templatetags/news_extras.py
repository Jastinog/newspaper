from django import template

from apps.news.models import Feed

register = template.Library()

LEAN_COLORS = {
    "left": "#2962ff",
    "center_left": "#42a5f5",
    "center": "#9e9e9e",
    "center_right": "#ef6c00",
    "right": "#c62828",
}


@register.inclusion_tag("news/_bias_spectrum.html")
def bias_spectrum(item):
    """Render a Ground News-style coverage spectrum bar for a DigestItem."""
    counts = {value: 0 for value, _ in Feed.Lean.choices}
    total = 0

    for article in item.articles.all():
        lean = article.feed.lean
        if lean and lean in counts:
            counts[lean] += 1
            total += 1

    if total < 2:
        return {"show": False}

    segments = []
    for value, label in Feed.Lean.choices:
        count = counts[value]
        if count:
            pct = round(count / total * 100)
            segments.append({
                "label": label,
                "color": LEAN_COLORS[value],
                "pct": pct,
                "count": count,
            })

    return {"show": True, "total": total, "segments": segments}
