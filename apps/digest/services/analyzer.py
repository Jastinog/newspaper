import json
import logging

from apps.core.services.ai import OpenAIClient, OpenAIError, fix_truncated_json
from apps.core.services.utils import sanitize_text
from apps.digest.models import DigestConfig, DigestSection

logger = logging.getLogger(__name__)


class StoryAnalyzer:
    """Analyzes collected articles per section and identifies distinct stories with refined search queries."""

    def __init__(self, client: OpenAIClient = None, config: DigestConfig = None):
        self.client = client or OpenAIClient()
        self.config = config or DigestConfig.get()

    def _build_article_list(self, articles: list[dict]) -> str:
        lines = []
        for a in articles:
            title = sanitize_text(a["title"])
            feed = sanitize_text(a["feed"])
            pub = a["published"]
            snippet = sanitize_text(a["snippet"][:self.config.article_snippet_length])
            date_part = f", {pub}" if pub else ""
            snippet_part = f" -- {snippet}" if snippet else ""
            lines.append(f'- [ID:{a["id"]}] "{title}" ({feed}{date_part}){snippet_part}')
        return "\n".join(lines)

    def analyze(self, section: DigestSection, articles: list[dict]) -> tuple[list[dict], dict]:
        """Identify distinct stories within a section's articles.

        Returns:
            (stories, usage) where stories = [{"label": str, "article_ids": [int], "search_queries": [str]}, ...]
        """
        if not articles:
            return [], {}

        cfg = self.config
        section_name = section.get_name("en")

        # Use per-section override if available
        prompt_template = section.system_prompt_override or cfg.system_prompt_analysis
        system = prompt_template.format(
            section=section_name,
            min=cfg.items_per_section_min,
            max=cfg.items_per_section_max,
        )

        user = f"Articles on {section_name}:\n\n{self._build_article_list(articles)}"

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.chat_model,
            max_tokens=cfg.max_tokens_analysis,
            temperature=cfg.temperature,
            response_format={"type": "json_object"},
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError as e:
            raise OpenAIError(
                f"Failed to parse analysis for '{section_name}': {e}\n"
                f"Response (first 300 chars): {fixed[:300]}"
            )

        stories = data.get("stories", [])
        logger.info("[%d] %s: %d stories identified, %s tokens",
                     section.order, section.slug, len(stories),
                     usage.get("total_tokens", 0))

        return stories, usage
