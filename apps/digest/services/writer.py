import json
import logging

from apps.core.services.ai import OpenAIClient, count_tokens, trim_to_tokens
from apps.core.services.utils import sanitize_text
from apps.digest.models import DigestConfig

logger = logging.getLogger(__name__)


def build_writer_schema(lang_codes: list[str]) -> dict:
    """Build a JSON Schema that guarantees all languages are returned."""
    lang_obj = {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["topic", "summary"],
        "additionalProperties": False,
    }
    properties = {code: lang_obj for code in lang_codes}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "news_item",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(lang_codes),
                "additionalProperties": False,
            },
        },
    }


class StoryWriter:
    """Writes a single news story with multilingual output — the 'journalist'."""

    def __init__(self, client: OpenAIClient = None, config: DigestConfig = None):
        self.client = client or OpenAIClient()
        self.config = config or DigestConfig.get()

    def write(self, story_plan: dict, articles_by_id: dict,
              languages: list[tuple[str, str]],
              schema: dict = None) -> tuple[dict, dict]:
        """Write one story item in all languages.

        Args:
            story_plan: {"label", "section", "article_ids", "angle"}
            articles_by_id: {id: Article} ORM objects with content
            languages: [(code, name), ...]

        Returns:
            (by_lang, usage) where:
                by_lang = {"en": {"topic": str, "summary": str}, ...}
        """
        cfg = self.config
        label = story_plan.get("label", "Unknown")
        angle = story_plan.get("angle", "")

        article_ids = story_plan.get("article_ids", [])[:cfg.edition_max_articles_per_story]
        article_text = self._build_article_context(article_ids, articles_by_id, cfg)

        if not article_text:
            empty = {code: {"topic": label, "summary": ""} for code, _ in languages}
            return empty, {}

        lang_codes = [code for code, _ in languages]
        lang_labels = ", ".join(f"{name} ({code})" for code, name in languages)
        system = cfg.system_prompt_writer.format(angle=angle, languages=lang_labels)
        user = f"Story: {label}\n\nArticles:\n\n{article_text}"

        response_format = schema or build_writer_schema(lang_codes)

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_generation,
            temperature=cfg.temperature,
            response_format=response_format,
        )

        data = json.loads(content)

        by_lang = {
            code: {"topic": data[code]["topic"], "summary": data[code]["summary"]}
            for code in lang_codes
        }
        return by_lang, usage

    def _build_article_context(self, article_ids: list[int],
                               articles_by_id: dict, cfg: DigestConfig) -> str:
        budget = cfg.edition_writer_budget_tokens
        used = 0
        parts = []
        for aid in article_ids:
            article = articles_by_id.get(aid)
            if not article or not article.content:
                continue
            title = sanitize_text(article.title)
            feed = article.feed.title if article.feed else ""
            pub = article.published.strftime("%Y-%m-%d") if article.published else ""

            remaining = budget - used
            if remaining <= 0:
                break
            per_article = min(cfg.edition_article_body_tokens, remaining)
            content = trim_to_tokens(sanitize_text(article.content), per_article)
            actual = count_tokens(content)

            header = f'[ID:{aid}] "{title}" ({feed}, {pub})'
            parts.append(f"{header}\n{content}")
            used += actual
        return "\n\n---\n\n".join(parts)
