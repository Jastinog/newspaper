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
        label = story.get("label", "Unknown")

        if not articles:
            empty_lang = {code: {"topic": label, "summary": ""} for code, _ in languages}
            return empty_lang, {"importance": 0}, {}

        cfg = self.config
        lang_labels = ", ".join(f"{name} ({code})" for code, name in languages)

        system = cfg.system_prompt_generation.format(languages=lang_labels)
        user = (
            f"Story: {label}\n\n"
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

        lang_codes = {code for code, _ in languages}
        max_attempts = 5
        data = None
        usage = {}
        last_error = None

        for attempt in range(max_attempts):
            try:
                content, usage = self.client.chat(**chat_kwargs)
                fixed = fix_truncated_json(content)
                data = json.loads(fixed)
            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(
                    "JSON parse failed for '%s' (attempt %d/%d): %s",
                    label, attempt + 1, max_attempts, e,
                )
                continue

            # Validate all languages are present with non-empty topic+summary
            missing = [
                code for code in lang_codes
                if not isinstance(data.get(code), dict)
                or not data[code].get("topic")
                or not data[code].get("summary")
            ]

            if not missing:
                break

            last_error = f"missing languages: {missing}"
            logger.warning(
                "Incomplete response for '%s' (attempt %d/%d): %s",
                label, attempt + 1, max_attempts, last_error,
            )
            data = None

        if data is None:
            raise OpenAIError(
                f"Failed to generate '{label}' after {max_attempts} "
                f"attempts: {last_error}"
            )

        common = {
            "importance": data.get("importance", 0),
        }

        by_lang = {
            code: {"topic": data[code]["topic"], "summary": data[code]["summary"]}
            for code, _ in languages
        }

        return by_lang, common, usage
