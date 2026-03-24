import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from apps.billing.models import APIUsage
from apps.digest.models import Digest, DigestTopic
from apps.core.services.ai import MODEL_MINI, OpenAIClient, calculate_cost

from .collector import TopicArticleCollector
from .generator import LANGUAGES, HeadlineGenerator, TopicDigestGenerator
from .saver import DigestSaver

logger = logging.getLogger(__name__)


class DigestService:
    """Orchestrates parallel digest pipeline: collect by topic → generate → save."""

    def __init__(self, client: OpenAIClient = None, hours=36, per_topic=25):
        self.client = client
        self.collector = TopicArticleCollector(hours=hours, per_topic=per_topic)
        self.saver = DigestSaver()

    def _generate_topic(self, topic: DigestTopic, articles: list[dict]) -> dict:
        """Generate digest items for a single topic (runs in thread)."""
        generator = TopicDigestGenerator(client=self.client, topic=topic)
        logger.info("Generating [%d] %s with %d articles...",
                     topic.order, topic.name_en, len(articles))
        result = generator.generate(articles)
        usage = result.get("usage", {})
        logger.info("[%d] %s done: %d items, %d tokens",
                     topic.order, topic.name_en,
                     len(result.get("items", [])),
                     usage.get("total_tokens", 0))
        return result

    def run(self, digest_date: date = None, languages: list[str] = None) -> list[Digest]:
        digest_date = digest_date or date.today()
        languages = languages or LANGUAGES

        # 1. Collect articles per topic via embeddings
        topic_articles = self.collector.collect()
        total = sum(len(articles) for _, articles in topic_articles)
        if total == 0:
            raise RuntimeError("No articles found via topic embeddings. Check embeddings and topics.")

        valid_article_ids = {a["id"] for _, articles in topic_articles for a in articles}

        # 2. Generate all topics in parallel
        topic_results = []
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        with ThreadPoolExecutor(max_workers=len(topic_articles)) as executor:
            futures = {
                executor.submit(self._generate_topic, topic, articles): topic.pk
                for topic, articles in topic_articles
            }
            for future in as_completed(futures):
                result = future.result()
                topic_results.append(result)
                for key in total_usage:
                    total_usage[key] += result.get("usage", {}).get(key, 0)

        # 3. Generate headline
        headline_gen = HeadlineGenerator(client=self.client)
        headlines, headline_usage = headline_gen.generate(topic_results)
        for key in total_usage:
            total_usage[key] += headline_usage.get(key, 0)

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
            logger.info("Digest saved: %s [%s]", digest, digest.language)

        return digests
