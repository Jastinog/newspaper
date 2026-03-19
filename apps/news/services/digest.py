import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from django.db.models import Max

from apps.news.models import APIUsage, Article, Digest, DigestItem, DigestSection

from .openai_client import MODEL_MINI, OpenAIClient, OpenAIError, calculate_cost, fix_truncated_json
from .topic_collector import TopicArticleCollector

logger = logging.getLogger(__name__)

LANGUAGES = ["en", "ru", "uk"]

TOPICS = {
    "en": [
        "AI • Technology",
        "World Politics",
        "Business • Economy",
        "Science • Health",
        "War • Conflicts",
        "Crime • Justice",
        "Cybersecurity • Privacy",
        "Energy • Climate",
        "Sports • Entertainment",
        "Society • Culture",
    ],
    "ru": [
        "AI • Технологии",
        "Мировая политика",
        "Бизнес • Экономика",
        "Наука • Здоровье",
        "Война • Конфликты",
        "Криминал • Правосудие",
        "Кибербезопасность • Приватность",
        "Энергетика • Климат",
        "Спорт • Развлечения",
        "Общество • Культура",
    ],
    "uk": [
        "AI • Технології",
        "Світова політика",
        "Бізнес • Економіка",
        "Наука • Здоров'я",
        "Війна • Конфлікти",
        "Кримінал • Правосуддя",
        "Кібербезпека • Приватність",
        "Енергетика • Клімат",
        "Спорт • Розваги",
        "Суспільство • Культура",
    ],
}


def _sanitize(s: str) -> str:
    """Remove control characters except newline/tab."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)


class TopicDigestGenerator:
    """Generates digest items for a single topic in all languages at once."""

    def __init__(self, client: OpenAIClient = None, topic_index: int = 0):
        self.client = client or OpenAIClient()
        self.topic_index = topic_index
        self.topic_names = {lang: TOPICS[lang][topic_index] for lang in LANGUAGES}

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
        """Generate items for this topic. Returns {topic_index, topic_names, items, usage}."""
        if not articles:
            return {
                "topic_index": self.topic_index,
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
                f"Failed to parse topic {self.topic_index} JSON: {e}\n"
                f"Response (first 300 chars): {fixed[:300]}"
            )

        return {
            "topic_index": self.topic_index,
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


def _localized(value, lang: str) -> str:
    """Extract a localized string from a multilingual dict or plain value."""
    if isinstance(value, dict):
        return value.get(lang, value.get("en", ""))
    return str(value)


class DigestSaver:
    """Saves multilingual digest from parallel topic results."""

    def save(
        self,
        digest_date: date,
        topic_results: list[dict],
        headlines: dict,
        languages: list[str],
        valid_article_ids: set,
    ) -> list[Digest]:
        """Create Digest records for each language from topic results."""
        digests = []

        for lang in languages:
            Digest.objects.filter(date=digest_date, language=lang).delete()

            digest = Digest.objects.create(
                date=digest_date,
                language=lang,
                headline=headlines.get(lang, ""),
            )

            for topic_result in sorted(topic_results, key=lambda r: r["topic_index"]):
                topic_idx = topic_result["topic_index"]
                section = DigestSection.objects.create(
                    digest=digest,
                    title=topic_result["topic_names"].get(lang, TOPICS["en"][topic_idx]),
                    order=topic_idx,
                )

                for j, item_data in enumerate(topic_result.get("items", [])):
                    raw_importance = item_data.get("importance", 0)
                    importance = max(0, min(9, int(raw_importance))) if isinstance(raw_importance, (int, float)) else 0

                    item = DigestItem.objects.create(
                        section=section,
                        topic=_localized(item_data.get("topic", {}), lang),
                        summary=_localized(item_data.get("summary", {}), lang),
                        order=j,
                        importance=importance,
                    )

                    raw_ids = item_data.get("article_ids", [])
                    linked_ids = [aid for aid in raw_ids if aid in valid_article_ids]
                    if linked_ids:
                        item.articles.set(linked_ids)

            # Calculate freshness per section
            for section in digest.sections.all():
                newest = (
                    Article.objects
                    .filter(digest_items__section=section, published__isnull=False)
                    .aggregate(newest=Max("published"))["newest"]
                )
                if newest:
                    section.freshness = newest.timestamp()
                    section.save(update_fields=["freshness"])

            digests.append(digest)

        return digests


class DigestService:
    """Orchestrates parallel digest pipeline: collect by topic → generate → save."""

    def __init__(self, client: OpenAIClient = None, hours=72, per_topic=25):
        self.client = client
        self.collector = TopicArticleCollector(hours=hours, per_topic=per_topic)
        self.saver = DigestSaver()

    def _generate_topic(self, topic_index: int, articles: list[dict]) -> dict:
        """Generate digest items for a single topic (runs in thread)."""
        generator = TopicDigestGenerator(client=self.client, topic_index=topic_index)
        logger.info("Generating topic %d (%s) with %d articles...",
                     topic_index, TOPICS["en"][topic_index], len(articles))
        result = generator.generate(articles)
        usage = result.get("usage", {})
        logger.info("Topic %d done: %d items, %d tokens",
                     topic_index, len(result.get("items", [])),
                     usage.get("total_tokens", 0))
        return result

    def run(self, digest_date: date = None, languages: list[str] = None) -> list[Digest]:
        digest_date = digest_date or date.today()
        languages = languages or LANGUAGES

        # 1. Collect articles per topic via embeddings
        topic_articles = self.collector.collect()
        total = sum(len(v) for v in topic_articles.values())
        if total == 0:
            raise RuntimeError("No articles found via topic embeddings. Check embeddings and seed_topics.")

        valid_article_ids = {a["id"] for articles in topic_articles.values() for a in articles}

        # 2. Generate all topics in parallel (10 threads)
        topic_results = []
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def _accum_usage(usage):
            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self._generate_topic, idx, articles): idx
                for idx, articles in topic_articles.items()
            }
            for future in as_completed(futures):
                result = future.result()
                topic_results.append(result)
                _accum_usage(result.get("usage", {}))

        # 3. Generate headline
        headline_gen = HeadlineGenerator(client=self.client)
        headlines, headline_usage = headline_gen.generate(topic_results)
        _accum_usage(headline_usage)

        logger.info("All topics + headline generated: %d total tokens", total_usage["total_tokens"])

        # 4. Save digests for each language
        digests = self.saver.save(
            digest_date=digest_date,
            topic_results=topic_results,
            headlines=headlines,
            languages=languages,
            valid_article_ids=valid_article_ids,
        )

        # 5. Log API usage (split evenly across language digests)
        num_langs = len(digests)
        per_lang_prompt = total_usage["prompt_tokens"] // num_langs
        per_lang_completion = total_usage["completion_tokens"] // num_langs
        per_lang_total = total_usage["total_tokens"] // num_langs

        for digest in digests:
            APIUsage.objects.create(
                service=APIUsage.Service.DIGEST,
                api_type=APIUsage.APIType.CHAT,
                model=MODEL_MINI,
                prompt_tokens=per_lang_prompt,
                completion_tokens=per_lang_completion,
                total_tokens=per_lang_total,
                cost_usd=calculate_cost(MODEL_MINI, per_lang_prompt, per_lang_completion),
                digest=digest,
            )

        for d in digests:
            logger.info("Digest saved: %s [%s]", d, d.language)

        return digests
