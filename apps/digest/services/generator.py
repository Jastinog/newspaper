import json
import logging

from apps.core.services.ai import OpenAIClient, OpenAIError, fix_truncated_json
from apps.core.services.utils import sanitize_text
from apps.digest.models import DigestConfig

logger = logging.getLogger(__name__)


class ItemGenerator:
    """Generates a single news item in the default language from refined articles."""

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

    def generate(self, story: dict, articles: list[dict]) -> tuple[dict, dict]:
        """Generate one news item from a story and its articles.

        Returns:
            (item_data, usage) where item_data = {"topic": str, "summary": str, "importance": int, "article_ids": [int]}
        """
        if not articles:
            return {
                "topic": story.get("label", ""),
                "summary": "",
                "importance": 0,
                "article_ids": [],
            }, {}

        cfg = self.config
        system = cfg.system_prompt_generation
        user = (
            f"Story: {story.get('label', 'Unknown')}\n\n"
            f"Articles:\n\n{self._build_article_list(articles)}"
        )

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_generation,
            temperature=cfg.temperature,
            response_format={"type": "json_object"},
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError as e:
            raise OpenAIError(
                f"Failed to parse item for '{story.get('label')}': {e}\n"
                f"Response (first 300 chars): {fixed[:300]}"
            )

        return data, usage


class HeadlineGenerator:
    """Generates a headline for the digest in the default language."""

    def __init__(self, client: OpenAIClient = None, config: DigestConfig = None):
        self.client = client or OpenAIClient()
        self.config = config or DigestConfig.get()

    def generate(self, items: list[dict]) -> tuple[str, dict]:
        """Generate headline from top items. Returns (headline_str, usage)."""
        top_labels = []
        for item in items:
            imp = item.get("importance", 0)
            topic = item.get("topic", "")
            if imp >= 4 and topic:
                top_labels.append((imp, topic))

        top_labels.sort(key=lambda x: x[0], reverse=True)
        labels = [t[1] for t in top_labels[:20]]

        if not labels:
            return "", {}

        cfg = self.config
        system = cfg.system_prompt_headline
        user = "Top stories today:\n" + "\n".join(f"- {t}" for t in labels)

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_headline,
            temperature=cfg.temperature,
            response_format={"type": "json_object"},
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
            headline = data.get("headline", "")
        except json.JSONDecodeError:
            headline = ""

        return headline, usage
