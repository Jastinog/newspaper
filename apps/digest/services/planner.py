import json
import logging

from apps.core.services.ai import OpenAIClient, fix_truncated_json
from apps.core.services.utils import sanitize_text
from apps.digest.models import DigestConfig

logger = logging.getLogger(__name__)


def build_planner_schema() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "edition_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "stories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "section": {"type": "string"},
                                "article_ids": {"type": "array", "items": {"type": "integer"}},
                                "importance": {"type": "integer"},
                                "angle": {"type": "string"},
                            },
                            "required": ["label", "section", "article_ids", "importance", "angle"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["stories"],
                "additionalProperties": False,
            },
        },
    }


class EditionPlanner:
    """Plans the entire edition in one LLM call — the 'editor-in-chief'."""

    def __init__(self, client: OpenAIClient = None, config: DigestConfig = None):
        self.client = client or OpenAIClient()
        self.config = config or DigestConfig.get()

    def plan(self, articles: list[dict], sections: list,
             items_per_section: int = None,
             on_event=None) -> tuple[list[dict], dict]:
        cfg = self.config
        ips = items_per_section or cfg.edition_items_per_section

        article_cards = self._build_article_cards(articles)
        section_list = self._build_section_list(sections)

        system = cfg.system_prompt_planner.format(
            sections=section_list,
            items_per_section=ips,
            total=ips * len(sections),
        )
        user = f"Articles published in the last 24 hours ({len(articles)} total):\n\n{article_cards}"

        content, usage = self.client.chat(
            system=system,
            user=user,
            model=cfg.planner_model,
            max_tokens=16000,
            temperature=cfg.temperature,
            response_format=build_planner_schema(),
            timeout=300,
        )

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from planner, attempting repair")
            data = json.loads(fix_truncated_json(content))

        stories = data.get("stories", [])

        valid_slugs = {s.slug for s in sections}
        stories = [s for s in stories if s.get("section") in valid_slugs]

        logger.info("Edition plan: %d stories, %s tokens",
                     len(stories), usage.get("total_tokens", 0))

        return stories, usage

    def _build_article_cards(self, articles: list[dict]) -> str:
        lines = []
        for a in articles:
            title = sanitize_text(a["title"])
            feed = sanitize_text(a.get("feed", ""))
            pub = a.get("published", "")
            snippet = sanitize_text(a.get("snippet", ""))
            date_part = f", {pub}" if pub else ""
            snippet_part = f"\n  {snippet}" if snippet else ""
            lines.append(f'[ID:{a["id"]}] "{title}" ({feed}{date_part}){snippet_part}')
        return "\n".join(lines)

    def _build_section_list(self, sections) -> str:
        lines = []
        for s in sections:
            name = s.get_name("en")
            desc = s.description or ""
            lines.append(f'- "{s.slug}": {name} — {desc}')
        return "\n".join(lines)
