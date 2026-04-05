import json
import logging

from apps.core.services.ai import OpenAIClient, OpenAIError, fix_truncated_json
from apps.core.services.utils import sanitize_text
from apps.digest.models import DigestConfig

logger = logging.getLogger(__name__)


class ItemGenerator:
    """Generates a single news item with translations in one API call."""

    def __init__(self, client: OpenAIClient = None, config: DigestConfig = None):
        self.client = client or OpenAIClient()
        self.config = config or DigestConfig.get()

    def _build_article_list(self, articles: list[dict]) -> str:
        lines = []
        for a in articles:
            title = sanitize_text(a["title"])
            feed = sanitize_text(a.get("feed", ""))
            pub = a.get("published", "")
            content = sanitize_text(a.get("content", ""))
            date_part = f", {pub}" if pub else ""
            content_part = f"\n  {content}" if content else ""
            lines.append(f'- [ID:{a["id"]}] "{title}" ({feed}{date_part}){content_part}')
        return "\n".join(lines)

    def generate(self, story: dict, articles: list[dict],
                 languages: list[tuple[str, str]]) -> tuple[dict, dict, dict]:
        """Generate one news item in all languages from a story and its articles.

        Args:
            story: {"label": str, "article_ids": [int], "search_queries": [str]}
            articles: refined article dicts with content
            languages: [(code, name), ...] all languages including default

        Returns:
            (by_lang, common, usage) where:
                by_lang = {"en": {"topic": str, "summary": str}, "ru": {...}, ...}
                common = {"importance": int}
        """
        if not articles:
            empty_lang = {code: {"topic": story.get("label", ""), "summary": ""} for code, _ in languages}
            return empty_lang, {"importance": 0}, {}

        cfg = self.config
        lang_labels = ", ".join(f"{name} ({code})" for code, name in languages)

        system = cfg.system_prompt_generation.format(languages=lang_labels)
        user = (
            f"Story: {story.get('label', 'Unknown')}\n\n"
            f"Articles:\n\n{self._build_article_list(articles)}"
        )

        chat_kwargs = dict(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_generation,
            temperature=cfg.temperature,
            response_format={"type": "json_object"},
        )

        data = None
        last_error = None
        for attempt in range(2):
            content, usage = self.client.chat(**chat_kwargs)
            fixed = fix_truncated_json(content)
            try:
                data = json.loads(fixed)
                break
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(
                    "JSON parse failed for '%s' (attempt %d): %s",
                    story.get("label"), attempt + 1, e,
                )

        if data is None:
            raise OpenAIError(
                f"Failed to parse item for '{story.get('label')}' after 2 attempts: {last_error}\n"
                f"Response (first 300 chars): {fixed[:300]}"
            )

        common = {
            "importance": data.get("importance", 0),
        }

        by_lang = {}
        for code, _ in languages:
            lang_data = data.get(code, {})
            if isinstance(lang_data, dict):
                by_lang[code] = {
                    "topic": lang_data.get("topic", ""),
                    "summary": lang_data.get("summary", ""),
                }

        return by_lang, common, usage
