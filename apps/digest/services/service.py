import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from django.db import close_old_connections
from django.utils import timezone

from apps.billing.models import APIUsage
from apps.billing.services import record_digest_usage
from apps.core.models import Language
from apps.core.services.ai import (
    EMBEDDING_MODEL, OpenAIClient, EmbeddingClient,
)
from apps.digest.models import (
    ArticleUse, Digest, DigestConfig, DigestItemTranslation, DigestTranslation, ItemPipeline,
)

from .analyzer import StoryAnalyzer
from .collector import SectionArticleCollector
from .deduplicator import StoryDeduplicator
from .generator import HeadlineGenerator, ItemGenerator
from .refiner import StoryRefiner
from .saver import DigestSaver
from .translator import ItemTranslator

logger = logging.getLogger(__name__)

class DigestService:
    """Digest pipeline with parallel story processing and batched translations.

    Pipeline phases:
      A. Collect articles per section (embedding search)
      B. Analyze each section -> identify stories
      C. Deduplicate stories across sections
      D. Process stories in parallel: refine -> generate -> save
      E. Batch-translate all items
      F. Generate & translate headline
    """

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
        self.deduplicator = StoryDeduplicator(embedder=self.embedder)
        self.saver = DigestSaver()

    def run(self, digest_date: date = None, languages: list[str] = None) -> Digest:
        digest_date = digest_date or date.today()
        default_lang = Language.default()
        if not default_lang:
            raise RuntimeError("No default language set. Run initdigest first.")

        if languages:
            target_langs = list(
                Language.active_targets().filter(code__in=languages)
            )
        else:
            target_langs = list(Language.active_targets())

        # Fresh run
        Digest.objects.filter(date=digest_date).delete()
        digest = Digest.objects.create(date=digest_date)

        # Phase A: Collect
        section_articles = self.collector.collect()
        total = sum(len(a) for _, a in section_articles)
        if total == 0:
            raise RuntimeError("No articles found. Check embeddings and sections.")

        # Phase B: Analyze all sections
        section_stories = []
        for section, articles in section_articles:
            try:
                stories, usage = self.analyzer.analyze(section, articles)
                record_digest_usage(usage, step=APIUsage.Step.ANALYZE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest)
                if stories:
                    section_stories.append((section, stories))
            except Exception:
                logger.exception("Analysis failed for [%s]", section.slug)

        # Phase C: Deduplicate across sections
        section_stories = self.deduplicator.deduplicate(section_stories)

        # Phase D: Process stories in parallel (refine -> generate -> save)
        used_ids = set(ArticleUse.objects.values_list("article_id", flat=True))
        items_with_data = self._process_all_stories(digest, section_stories, default_lang, used_ids)

        if not items_with_data:
            raise RuntimeError("No items generated.")

        # Phase E: Batch-translate all items
        if target_langs:
            self._translate_all(digest, items_with_data, target_langs)

        # Phase F: Headline
        items_data = [
            {"topic": row["topic"], "importance": row["item__importance"]}
            for row in DigestItemTranslation.objects
            .filter(item__digest=digest, language=default_lang)
            .values("topic", "item__importance")
        ]
        headline, usage = self.headline_generator.generate(items_data)
        record_digest_usage(usage, step=APIUsage.Step.HEADLINE,
                            api_type=APIUsage.APIType.CHAT,
                            model=self.config.chat_model, digest=digest)
        DigestTranslation.objects.create(digest=digest, language=default_lang, headline=headline)

        # Translate headline
        for lang in target_langs:
            try:
                translated_headline, h_usage = self.translator.translate_headline(headline, lang.name)
                record_digest_usage(h_usage, step=APIUsage.Step.TRANSLATE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest)
                self.saver.save_translations(digest, lang, [], translated_headline)
            except Exception:
                logger.exception("Headline translation to %s failed", lang.code)

        digest.stage = Digest.Stage.DONE
        digest.save(update_fields=["stage"])

        logger.info("Digest %s complete: %d items", digest.date, digest.items.count())
        return digest

    def _process_all_stories(self, digest, section_stories, default_lang, used_ids):
        """Process sections sequentially, stories within each section in parallel.

        After each section completes, used_ids and used_image_ids are updated so
        the next section never picks the same articles or images.
        """
        items_with_data = []
        used_image_ids = set()

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            for section, stories in section_stories:
                futures = {
                    executor.submit(
                        self._process_story_safe, digest, section, story,
                        default_lang, used_ids,
                    ): story
                    for story in stories
                }
                section_items = []
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        section_items.append(result)

                for item, item_data in section_items:
                    article_ids = item_data.get("article_ids", [])
                    image_id = self.saver.assign_image(item, used_image_ids, article_ids)
                    if image_id:
                        used_image_ids.add(image_id)
                    used_ids.update(article_ids)

                items_with_data.extend(section_items)

        return items_with_data

    def _process_story_safe(self, digest, section, story, default_lang, used_ids):
        """Thread-safe wrapper: close stale DB connections around story processing."""
        close_old_connections()
        try:
            return self._process_story(digest, section, story, default_lang, used_ids)
        except Exception:
            logger.exception("Story '%s' failed, skipping", story.get("label", "?"))
            return None
        finally:
            close_old_connections()

    def _process_story(self, digest, section, story, default_lang, used_ids):
        """Process one story: refine -> generate -> save. Returns (item, item_data) or None."""
        refined, refine_usage = self.refiner.refine(story, used_ids=used_ids)
        if not refined:
            return None

        item_data, gen_usage = self.item_generator.generate(story, refined)

        item = self.saver.save_item(digest, section, story, item_data, refined, default_lang)

        # Record per-step usage
        record_digest_usage(refine_usage, step=APIUsage.Step.REFINE,
                            api_type=APIUsage.APIType.EMBEDDING,
                            model=EMBEDDING_MODEL, digest=digest, item=item)
        record_digest_usage(gen_usage, step=APIUsage.Step.GENERATE,
                            api_type=APIUsage.APIType.CHAT,
                            model=self.config.chat_model, digest=digest, item=item)

        return item, item_data

    def _translate_all(self, digest, items_with_data, target_langs):
        """Translate all items in parallel — one API call per item, all languages at once."""
        lang_pairs = [(lang.code, lang.name) for lang in target_langs]
        per_lang = {lang.code: [] for lang in target_langs}
        translated_item_ids = set()

        def _translate_one(item, item_data):
            close_old_connections()
            try:
                topic = item_data.get("topic", "")
                summary = item_data.get("summary", "")
                by_lang, usage = self.translator.translate_item_multilang(
                    topic, summary, lang_pairs,
                )
                return item, by_lang, usage
            except Exception:
                logger.exception("Translation failed for item #%s", item.pk)
                return item, {}, {}
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {
                executor.submit(_translate_one, item, data): item
                for item, data in items_with_data
            }
            for future in as_completed(futures):
                item, by_lang, usage = future.result()
                if not by_lang:
                    continue
                for lang in target_langs:
                    translated = by_lang.get(lang.code)
                    if translated:
                        per_lang[lang.code].append((item, translated))
                record_digest_usage(usage, step=APIUsage.Step.TRANSLATE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest, item=item)
                translated_item_ids.add(item.pk)

        for lang in target_langs:
            if per_lang[lang.code]:
                self.saver.save_translations(digest, lang, per_lang[lang.code], "")

        if translated_item_ids:
            ItemPipeline.objects.filter(
                item_id__in=translated_item_ids, translated_at__isnull=True,
            ).update(translated_at=timezone.now())
