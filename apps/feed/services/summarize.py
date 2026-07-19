"""On-demand Russian summary ("суть без воды" + вывод) for a single article.

Reuses the shared OpenAIClient. The result is persisted in ArticleSummary so the
same article is never summarized twice — tokens are spent once, on demand.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils.html import strip_tags

from apps.billing.models import APIUsage
from apps.billing.services import record_usage
from apps.core.services.ai import OpenAIClient, fix_truncated_json, trim_to_tokens
from apps.feed.models import ArticleSummary

logger = logging.getLogger(__name__)

# Cap the article text we send so a huge page can't blow up the prompt cost.
MAX_INPUT_TOKENS = 6000

SYSTEM_PROMPT = (
    "Ты — редактор новостей. Тебе дают заголовок и текст новости (на любом языке). "
    "Твоя задача — пересказать СУТЬ новости на русском языке, без воды: только то, "
    "что действительно важно (кто, что, где, когда, почему, что дальше). Держись близко "
    "к оригиналу, не добавляй фактов, которых нет в тексте, не выдумывай и не оценивай "
    "от себя. Пиши ясно и по делу.\n\n"
    "Верни строго JSON без markdown-обёрток такого вида:\n"
    '{"summary": "<пересказ сути в 1-3 абзацах>", '
    '"conclusion": "<краткий вывод в 1-2 предложениях: главное значение/итог>"}'
)


class SummaryError(Exception):
    pass


# Cap how many *new* (paid) summaries can be triggered per hour, across every
# transport (the HTTP endpoint and the WebSocket flow). Cached summaries are free
# and never hit these counters. This is the single spend guard for the feature:
#   - the per-peer key must be a trusted TCP peer (never a client-supplied
#     forwarding header), so callers pass it in from their own request context;
#   - the global ceiling uses no client input at all — an unspoofable hard bound.
_RATE_MAX = 20
_GLOBAL_MAX = 100
_RATE_WINDOW = 60 * 60


def _rate_incr(key, limit):
    """Increment a windowed counter; return True while at/under the limit."""
    cache.add(key, 0, _RATE_WINDOW)
    try:
        used = cache.incr(key)
    except ValueError:
        used = 1
    return used <= limit


def summary_rate_ok(peer):
    """True while both the per-peer and global hourly budgets are under cap.

    Increments both counters unconditionally so neither can be starved by the
    other's short-circuit. `peer` is the caller's trusted TCP peer identifier.
    """
    peer = peer or "unknown"
    peer_ok = _rate_incr(f"sumrl:{peer}", _RATE_MAX)
    global_ok = _rate_incr("sumrl:global", _GLOBAL_MAX)
    return peer_ok and global_ok


def generate_summary(article, *, client: OpenAIClient = None, progress_callback=None) -> ArticleSummary:
    """Call OpenAI, persist and return an ArticleSummary. Raises SummaryError.

    progress_callback(step, total, label) — optional, invoked at each real stage
    so a WebSocket consumer can stream honest progress to the browser.
    """
    def progress(step, label):
        if progress_callback:
            progress_callback(step, 3, label)

    progress(1, "Читаю статью")
    source = strip_tags(article.content or "").strip()
    if not source:
        raise SummaryError("Article has no text to summarize.")

    model = settings.OPENAI_SUMMARY_MODEL
    source = trim_to_tokens(source, MAX_INPUT_TOKENS)
    user = f"Заголовок: {article.title}\n\nТекст новости:\n{source}"

    progress(2, "Выделяю суть")
    client = client or OpenAIClient()
    try:
        content, usage = client.chat(
            system=SYSTEM_PROMPT,
            user=user,
            model=model,
            max_tokens=1200,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as e:  # OpenAIError and transport errors
        raise SummaryError(str(e)) from e

    try:
        data = json.loads(fix_truncated_json(content))
        summary_text = (data.get("summary") or "").strip()
        conclusion_text = (data.get("conclusion") or "").strip()
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error("Bad summary JSON for article %s: %s", article.pk, content[:300])
        raise SummaryError("Model returned malformed output.") from e

    if not summary_text:
        raise SummaryError("Model returned an empty summary.")

    progress(3, "Сохраняю")
    usage_row = record_usage(usage, service=APIUsage.Service.SUMMARY,
                             api_type=APIUsage.APIType.CHAT, model=model, article=article)

    summary, _ = ArticleSummary.objects.update_or_create(
        article=article,
        defaults={
            "summary": summary_text,
            "conclusion": conclusion_text,
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "cost_usd": usage_row.cost_usd if usage_row else 0,
        },
    )
    return summary
