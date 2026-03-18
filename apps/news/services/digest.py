import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from apps.news.models import APIUsage, Article, Digest, DigestItem, DigestSection

from .openai_client import MODEL_MINI, OpenAIClient, OpenAIError, calculate_cost, fix_truncated_json

logger = logging.getLogger(__name__)

TOPICS = [
    "AI & Технології",
    "Світова політика",
    "Економіка & Фінанси",
    "Наука & Космос",
    "Близький Схід & Конфлікти",
    "Суспільство & Культура",
    "Безпека & Кібер",
    "Енергетика & Клімат",
]


class ArticleCollector:
    """Collects recent articles for digest generation."""

    def __init__(self, limit=60, hours=72):
        self.limit = limit
        self.hours = hours

    def collect(self):
        """Return recent articles as list of dicts with id, title, feed, published, snippet."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.hours)
        articles = (
            Article.objects
            .select_related("feed")
            .filter(published__gte=cutoff)
            .order_by("-published")
            [:self.limit]
        )
        result = []
        for a in articles:
            snippet = a.summary or (a.content[:300] if a.content else "")
            result.append({
                "id": a.id,
                "title": a.title,
                "feed": a.feed.title if a.feed else "",
                "published": a.published.strftime("%Y-%m-%d") if a.published else "",
                "snippet": snippet,
            })
        return result


class DigestGenerator:
    """Generates a digest by calling OpenAI with collected articles."""

    def __init__(self, client: OpenAIClient = None, topics: list[str] = None):
        self.client = client or OpenAIClient()
        self.topics = topics or TOPICS

    def _build_article_list(self, articles: list[dict]) -> str:
        lines = []
        for a in articles:
            aid = a["id"]
            title = _sanitize(a["title"])
            feed = _sanitize(a["feed"])
            pub = a["published"]
            snippet = _sanitize(a["snippet"][:400])
            date_part = f", {pub}" if pub else ""
            snippet_part = f" -- {snippet}" if snippet else ""
            lines.append(f'- [ID:{aid}] "{title}" ({feed}{date_part}){snippet_part}')
        return "\n".join(lines)

    def _build_system_prompt(self) -> str:
        topics_str = ", ".join(f'"{t}"' for t in self.topics)
        return (
            "You are a world news analyst. Based on the provided recent news articles, "
            "create detailed thematic news tiles summarizing what is happening right now.\n\n"
            "Rules:\n"
            "- Each tile has 5-8 items. Each item covers one key development.\n"
            "- For each item provide:\n"
            '  - "topic": short name/event label (2-5 words, like a headline tag)\n'
            '  - "summary": detailed explanation of what happened, the context, '
            "key players involved, and why it matters (2-3 sentences)\n"
            '  - "article_ids": array of [ID:N] numbers from the input articles '
            "that this item is based on. Include ALL relevant article IDs.\n"
            "- CRITICAL: each news event or story MUST appear in ONLY ONE tile — the most relevant one. "
            "Do NOT repeat the same news across different tiles.\n"
            "- Do NOT reference article IDs in the topic or summary text — only in the article_ids array.\n"
            "- ALWAYS respond in Ukrainian (topic and summary must be in Ukrainian)\n"
            "- Output ONLY valid JSON, no markdown fences\n\n"
            f"Create EXACTLY {len(self.topics)} tiles on these topics: {topics_str}\n"
            'Also provide a "headline" field: 2-3 sentences summarizing the overall news picture.\n\n'
            "JSON format:\n"
            '{"headline": "...", "sections": [{"title": "...", "items": ['
            '{"topic": "...", "summary": "...", "article_ids": [1, 2]}, ...]}, ...]}'
        )

    def generate(self, articles: list[dict]) -> dict:
        """Call OpenAI and return parsed {headline, sections} dict."""
        system = self._build_system_prompt()
        user = f"Here are the recent news articles:\n\n{self._build_article_list(articles)}"

        content, usage = self.client.chat(
            system=system,
            user=user,
            max_tokens=10000,
            temperature=0.3,
        )

        fixed = fix_truncated_json(content)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError as e:
            raise OpenAIError(
                f"Failed to parse digest JSON: {e}\n"
                f"Response (first 300 chars): {fixed[:300]}"
            )

        data["usage"] = usage
        return data


class DigestSaver:
    """Persists a generated digest to the database."""

    def save(self, digest_date: date, data: dict, valid_article_ids: set = None) -> Digest:
        """Create or replace a Digest for the given date."""
        valid_article_ids = valid_article_ids or set()

        # Delete existing digest for this date (regeneration)
        Digest.objects.filter(date=digest_date).delete()

        digest = Digest.objects.create(
            date=digest_date,
            headline=data.get("headline", ""),
        )

        sections = data.get("sections", [])
        for i, section_data in enumerate(sections):
            section = DigestSection.objects.create(
                digest=digest,
                title=section_data.get("title", ""),
                order=i,
            )

            items = section_data.get("items", [])
            for j, item_data in enumerate(items):
                item = DigestItem.objects.create(
                    section=section,
                    topic=item_data.get("topic", ""),
                    summary=item_data.get("summary", ""),
                    order=j,
                )
                # Link source articles via M2M
                raw_ids = item_data.get("article_ids", [])
                linked_ids = [aid for aid in raw_ids if aid in valid_article_ids]
                if linked_ids:
                    item.articles.set(linked_ids)

        return digest


class DigestService:
    """Orchestrates the full digest pipeline: collect → generate → save."""

    def __init__(self, client: OpenAIClient = None, limit=60, hours=72):
        self.collector = ArticleCollector(limit=limit, hours=hours)
        self.generator = DigestGenerator(client=client)
        self.saver = DigestSaver()

    def run(self, digest_date: date = None) -> Digest:
        digest_date = digest_date or date.today()

        articles = self.collector.collect()
        if not articles:
            raise RuntimeError("No recent articles found. Run fetch_feeds first.")

        valid_article_ids = {a["id"] for a in articles}

        logger.info("Generating digest for %s with %d articles...", digest_date, len(articles))
        data = self.generator.generate(articles)

        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        logger.info(
            "Digest generated: %d sections, %d tokens",
            len(data.get("sections", [])),
            total_tokens,
        )

        digest = self.saver.save(digest_date, data, valid_article_ids)

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        APIUsage.objects.create(
            service=APIUsage.Service.DIGEST,
            api_type=APIUsage.APIType.CHAT,
            model=MODEL_MINI,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=calculate_cost(MODEL_MINI, prompt_tokens, completion_tokens),
            digest=digest,
        )

        logger.info("Digest saved: %s", digest)
        return digest


def _sanitize(s: str) -> str:
    """Remove control characters except newline/tab."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
