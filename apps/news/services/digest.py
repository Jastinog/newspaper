import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from django.db.models import Max

from apps.news.models import APIUsage, Article, Digest, DigestItem, DigestSection

from .openai_client import MODEL_MINI, OpenAIClient, OpenAIError, calculate_cost, fix_truncated_json

logger = logging.getLogger(__name__)

TOPICS = {
    "en": [
        "AI & Technology",
        "World Politics",
        "Economy & Finance",
        "Science & Space",
        "Middle East & Conflicts",
        "Society & Culture",
        "Security & Cyber",
        "Energy & Climate",
    ],
    "ru": [
        "AI & Технологии",
        "Мировая политика",
        "Экономика & Финансы",
        "Наука & Космос",
        "Ближний Восток & Конфликты",
        "Общество & Культура",
        "Безопасность & Кибер",
        "Энергетика & Климат",
    ],
    "uk": [
        "AI & Технології",
        "Світова політика",
        "Економіка & Фінанси",
        "Наука & Космос",
        "Близький Схід & Конфлікти",
        "Суспільство & Культура",
        "Безпека & Кібер",
        "Енергетика & Клімат",
    ],
}

LANGUAGE_INSTRUCTIONS = {
    "en": "ALWAYS respond in English (topic and summary must be in English)",
    "ru": "ALWAYS respond in Russian (topic and summary must be in Russian)",
    "uk": "ALWAYS respond in Ukrainian (topic and summary must be in Ukrainian)",
}


class ArticleCollector:
    """Collects recent articles for digest generation."""

    def __init__(self, limit=150, hours=72):
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

    def __init__(self, client: OpenAIClient = None, language: str = "uk"):
        self.client = client or OpenAIClient()
        self.language = language
        self.topics = TOPICS.get(language, TOPICS["en"])

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
            "- Each tile MUST have EXACTLY 8 items. Each item covers one key development.\n"
            "- For each item provide:\n"
            '  - "topic": short name/event label (2-5 words, like a headline tag)\n'
            '  - "summary": detailed explanation of what happened, the context, '
            "key players involved, and why it matters (2-3 sentences)\n"
            '  - "article_ids": array of [ID:N] numbers from the input articles '
            "that this item is based on. Include ALL relevant article IDs.\n"
            "- CRITICAL: each news event or story MUST appear in ONLY ONE tile — the most relevant one. "
            "Do NOT repeat the same news across different tiles.\n"
            "- Do NOT reference article IDs in the topic or summary text — only in the article_ids array.\n"
            f"- {LANGUAGE_INSTRUCTIONS.get(self.language, LANGUAGE_INSTRUCTIONS['en'])}\n"
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
            max_tokens=16000,
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

    def save(self, digest_date: date, data: dict, language: str = "en", valid_article_ids: set = None) -> Digest:
        """Create or replace a Digest for the given date and language."""
        valid_article_ids = valid_article_ids or set()

        # Delete existing digest for this date+language (regeneration)
        Digest.objects.filter(date=digest_date, language=language).delete()

        digest = Digest.objects.create(
            date=digest_date,
            language=language,
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

        # Calculate freshness for each section based on newest linked article
        for section in digest.sections.all():
            newest = (
                Article.objects
                .filter(digest_items__section=section, published__isnull=False)
                .aggregate(newest=Max("published"))["newest"]
            )
            if newest:
                section.freshness = newest.timestamp()
                section.save(update_fields=["freshness"])

        return digest


class DigestService:
    """Orchestrates the full digest pipeline: collect → generate → save."""

    def __init__(self, client: OpenAIClient = None, limit=60, hours=72):
        self.collector = ArticleCollector(limit=limit, hours=hours)
        self.client = client
        self.saver = DigestSaver()

    def _run_single(self, language: str, articles: list[dict], digest_date: date, valid_article_ids: set) -> Digest:
        """Generate and save a digest for a single language."""
        generator = DigestGenerator(client=self.client, language=language)

        logger.info("Generating %s digest for %s with %d articles...", language, digest_date, len(articles))
        data = generator.generate(articles)

        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        logger.info(
            "Digest [%s] generated: %d sections, %d tokens",
            language,
            len(data.get("sections", [])),
            total_tokens,
        )

        digest = self.saver.save(digest_date, data, language=language, valid_article_ids=valid_article_ids)

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

        logger.info("Digest saved: %s [%s]", digest, language)
        return digest

    def run(self, digest_date: date = None, languages: list[str] = None) -> list[Digest]:
        digest_date = digest_date or date.today()
        languages = languages or list(TOPICS.keys())

        articles = self.collector.collect()
        if not articles:
            raise RuntimeError("No recent articles found. Run fetch_feeds first.")

        valid_article_ids = {a["id"] for a in articles}

        if len(languages) == 1:
            return [self._run_single(languages[0], articles, digest_date, valid_article_ids)]

        digests = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._run_single, lang, articles, digest_date, valid_article_ids): lang
                for lang in languages
            }
            for future in futures:
                digests.append(future.result())

        return digests


def _sanitize(s: str) -> str:
    """Remove control characters except newline/tab."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
