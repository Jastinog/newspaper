import json
import logging
import re

from apps.news.models import DigestTopic
from apps.news.services.ai import MODEL_MINI, OpenAIClient, OpenAIError, fix_truncated_json

logger = logging.getLogger(__name__)

LANGUAGES = ["en", "ru", "uk"]


def _sanitize(s: str) -> str:
    """Remove control characters except newline/tab."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)


class TopicDigestGenerator:
    """Generates digest items for a single topic in all languages at once."""

    def __init__(self, client: OpenAIClient = None, topic: DigestTopic = None):
        self.client = client or OpenAIClient()
        self.topic = topic
        self.topic_names = {lang: topic.get_name(lang) for lang in LANGUAGES}

    def _build_article_list(self, articles: list[dict]) -> str:
        lines = []
        for a in articles:
            title = _sanitize(a["title"])
            feed = _sanitize(a["feed"])
            pub = a["published"]
            snippet = _sanitize(a["snippet"][:400])
            date_part = f", {pub}" if pub else ""
            snippet_part = f" -- {snippet}" if snippet else ""
            lines.append(f'- [ID:{a["id"]}] "{title}" ({feed}{date_part}){snippet_part}')
        return "\n".join(lines)

    def _build_system_prompt(self, num_articles: int) -> str:
        target = "8-10" if num_articles >= 12 else "4-8"
        return (
            f'You are a world news analyst specializing in "{self.topic_names["en"]}". '
            "Based on the provided articles, create detailed news items about key developments.\n\n"
            "Rules:\n"
            f"- Create {target} items, each covering one distinct development. Minimum 4.\n"
            "- Each item MUST have text in 3 languages: English (en), Russian (ru), Ukrainian (uk).\n"
            "- For each item provide:\n"
            '  - "topic": {"en": "...", "ru": "...", "uk": "..."} — short event label (2-5 words)\n'
            '  - "summary": {"en": "...", "ru": "...", "uk": "..."} — what happened, context, '
            "why it matters (2-3 sentences)\n"
            '  - "importance": integer 0-9 (0=mundane, 1-3=minor, 4-6=notable, 7-8=major, 9=extreme). '
            "Most items should be 2-5, only extraordinary events deserve 7+.\n"
            '  - "article_ids": array of [ID:N] numbers from the input. Include ALL relevant IDs.\n'
            "- Do NOT reference article IDs in topic or summary text — only in article_ids.\n"
            "- Output ONLY valid JSON, no markdown fences.\n\n"
            "JSON format:\n"
            '{"items": [{"topic": {"en": "...", "ru": "...", "uk": "..."}, '
            '"summary": {"en": "...", "ru": "...", "uk": "..."}, '
            '"importance": 5, "article_ids": [1, 2]}, ...]}'
        )

    def generate(self, articles: list[dict]) -> dict:
        """Generate items for this topic. Returns {topic, topic_names, items, usage}."""
        if not articles:
            return {
                "topic": self.topic,
                "topic_names": self.topic_names,
                "items": [],
                "usage": {},
            }

        system = self._build_system_prompt(len(articles))
        user = f"Articles on {self.topic_names['en']}:\n\n{self._build_article_list(articles)}"

        content, usage = self.client.chat(
            system=system,
            user=user,
            max_tokens=6000,
            temperature=0.3,
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError as e:
            raise OpenAIError(
                f"Failed to parse topic '{self.topic.name_en}' JSON: {e}\n"
                f"Response (first 300 chars): {fixed[:300]}"
            )

        return {
            "topic": self.topic,
            "topic_names": self.topic_names,
            "items": data.get("items", []),
            "usage": usage,
        }


class HeadlineGenerator:
    """Generates a multilingual headline from all topic results."""

    def __init__(self, client: OpenAIClient = None):
        self.client = client or OpenAIClient()

    def generate(self, topic_results: list[dict]) -> tuple[dict, dict]:
        """Return ({en: headline, ru: headline, uk: headline}, usage)."""
        top_items = []
        for tr in topic_results:
            topic_en = tr["topic_names"]["en"]
            for item in tr.get("items", []):
                imp = item.get("importance", 0)
                topic_text = item.get("topic", {}).get("en", "")
                if imp >= 4 and topic_text:
                    top_items.append((imp, f"[{topic_en}] {topic_text}"))

        top_items.sort(key=lambda x: x[0], reverse=True)
        top_labels = [t[1] for t in top_items[:20]]

        if not top_labels:
            return {"en": "", "ru": "", "uk": ""}, {}

        system = (
            "You are a news editor. Based on today's top stories, write a 2-3 sentence "
            "headline summarizing the overall news picture. Provide in 3 languages.\n\n"
            'Output ONLY valid JSON: {"en": "...", "ru": "...", "uk": "..."}'
        )
        user = "Top stories today:\n" + "\n".join(f"- {t}" for t in top_labels)

        content, usage = self.client.chat(
            system=system,
            user=user,
            max_tokens=1000,
            temperature=0.3,
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            data = {"en": "", "ru": "", "uk": ""}

        return data, usage
