import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from apps.billing.models import APIUsage
from apps.core.models import Language
from apps.core.services.ai import OpenAIClient, EmbeddingClient, calculate_cost
from apps.digest.models import Digest, DigestConfig

from .analyzer import StoryAnalyzer
from .collector import SectionArticleCollector
from .generator import HeadlineGenerator, ItemGenerator
from .refiner import StoryRefiner
from .saver import DigestSaver
from .translator import ItemTranslator

logger = logging.getLogger(__name__)


class DigestService:
    """Orchestrates the digest pipeline: collect → analyze → refine → generate → translate."""

    def __init__(self, config: DigestConfig = None):
        self.config = config or DigestConfig.get()
        self.client = OpenAIClient()
        self.embedder = EmbeddingClient()
        self.collector = SectionArticleCollector(config=self.config)
        self.analyzer = StoryAnalyzer(client=self.client, config=self.config)
        self.refiner = StoryRefiner(embedder=self.embedder, config=self.config)
        self.item_generator = ItemGenerator(client=self.client, config=self.config)
        self.headline_generator = HeadlineGenerator(client=self.client, config=self.config)
        self.translator = ItemTranslator(client=self.client, config=self.config)
        self.saver = DigestSaver()

    def _process_section(self, section, articles):
        """Process a single section: analyze stories, refine articles, generate items."""
        # Step 2: Analyze - identify stories
        stories, analysis_usage = self.analyzer.analyze(section, articles)

        # Build article lookup
        articles_map = {a["id"]: a for a in articles}

        section_items = []
        section_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        for key in section_usage:
            section_usage[key] += analysis_usage.get(key, 0)

        for story in stories:
            # Step 3: Refine articles for this story
            refined_articles = self.refiner.refine(story, articles_map)

            if not refined_articles:
                continue

            # Step 4: Generate one item
            item_data, gen_usage = self.item_generator.generate(story, refined_articles)
            section_items.append(item_data)

            for key in section_usage:
                section_usage[key] += gen_usage.get(key, 0)

        logger.info("[%d] %s: %d items generated", section.order, section.slug, len(section_items))
        return section, section_items, section_usage

    def run(self, digest_date: date = None, languages: list[str] = None) -> Digest:
        """Run the full digest pipeline.

        Args:
            digest_date: Date for the digest (default: today)
            languages: Language codes to translate to (default: all non-default languages)

        Returns:
            The created Digest instance
        """
        digest_date = digest_date or date.today()
        config = self.config
        default_lang = Language.default()

        if not default_lang:
            raise RuntimeError("No default language set. Run initnews first.")

        # Determine target languages for translation
        if languages:
            target_langs = list(Language.objects.filter(code__in=languages).exclude(pk=default_lang.pk))
        else:
            target_langs = list(Language.objects.exclude(pk=default_lang.pk))

        # Step 1: Collect articles per section
        section_articles = self.collector.collect()
        total = sum(len(articles) for _, articles in section_articles)
        if total == 0:
            raise RuntimeError("No articles found. Check embeddings and sections.")

        # Steps 2-4: Process each section (parallel)
        all_section_items = []
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
            futures = {
                executor.submit(self._process_section, section, articles): section.pk
                for section, articles in section_articles
            }
            for future in as_completed(futures):
                section, items, usage = future.result()
                if items:
                    all_section_items.append((section, items))
                for key in total_usage:
                    total_usage[key] += usage.get(key, 0)

        # Flatten all items for headline
        all_items_flat = [item for _, items in all_section_items for item in items]

        # Step 5: Generate headline
        headline, headline_usage = self.headline_generator.generate(all_items_flat)
        for key in total_usage:
            total_usage[key] += headline_usage.get(key, 0)

        logger.info("Generated %d items across %d sections, %d tokens",
                     len(all_items_flat), len(all_section_items), total_usage["total_tokens"])

        # Step 6: Save digest with default language
        digest = self.saver.save(digest_date, all_section_items, headline)

        # Step 7: Translate to other languages (parallel per language)
        if target_langs:
            self._translate_all(digest, target_langs, total_usage)

        # Log API usage
        APIUsage.objects.create(
            service=APIUsage.Service.DIGEST,
            api_type=APIUsage.APIType.CHAT,
            model=config.chat_model,
            prompt_tokens=total_usage["prompt_tokens"],
            completion_tokens=total_usage["completion_tokens"],
            total_tokens=total_usage["total_tokens"],
            cost_usd=calculate_cost(
                config.chat_model,
                total_usage["prompt_tokens"],
                total_usage["completion_tokens"],
            ),
            digest=digest,
        )

        logger.info("Digest %s saved: %d items, %d tokens total",
                     digest_date, len(all_items_flat), total_usage["total_tokens"])

        return digest

    def _translate_all(self, digest: Digest, target_langs: list, total_usage: dict):
        """Translate all items and headline to target languages."""
        default_lang = Language.default()
        items = list(digest.items.prefetch_related("translations").all())

        # Get default language texts (iterate prefetched cache, no extra queries)
        item_texts = []
        for item in items:
            for t in item.translations.all():
                if t.language_id == default_lang.pk:
                    item_texts.append((item, t.topic, t.summary))
                    break

        headline_en = digest.get_headline(default_lang)

        for lang in target_langs:
            lang_name = lang.name  # capture before closure
            lang_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

            # Translate headline
            translated_headline, h_usage = self.translator.translate_headline(
                headline_en, lang_name,
            )
            for key in lang_usage:
                lang_usage[key] += h_usage.get(key, 0)

            # Translate items (parallel within language)
            item_translations = []

            def translate_one(item, topic, summary, _lang_name=lang_name):
                translated, usage = self.translator.translate_item(topic, summary, _lang_name)
                return item, translated, usage

            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                futures = [
                    executor.submit(translate_one, item, topic, summary)
                    for item, topic, summary in item_texts
                ]
                for future in as_completed(futures):
                    item, translated, usage = future.result()
                    item_translations.append((item, translated))
                    for key in lang_usage:
                        lang_usage[key] += usage.get(key, 0)

            # Save translations
            self.saver.save_translations(digest, lang, item_translations, translated_headline)

            for key in total_usage:
                total_usage[key] += lang_usage.get(key, 0)

            logger.info("Translated to %s: %d items, %d tokens",
                         lang.code, len(item_translations), lang_usage["total_tokens"])
