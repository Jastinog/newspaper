import logging
from datetime import date

from django.utils import timezone

from apps.billing.models import APIUsage
from apps.billing.services import record_digest_usage
from apps.core.models import Language
from apps.core.services.ai import (
    EMBEDDING_MODEL, OpenAIClient, EmbeddingClient,
)
from apps.digest.models import (
    Digest, DigestConfig, DigestTranslation, ItemPipeline,
)

from .analyzer import StoryAnalyzer
from .collector import SectionArticleCollector
from .generator import HeadlineGenerator, ItemGenerator
from .refiner import StoryRefiner
from .saver import DigestSaver
from .translator import ItemTranslator

logger = logging.getLogger(__name__)


class DigestService:
    """Sequential digest pipeline.

    Full batch: collect -> analyze -> refine -> generate -> headline -> translate.
    Each LLM/embedding call creates its own APIUsage record with step + item.
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
        self.saver = DigestSaver()

    def run(self, digest_date: date = None, languages: list[str] = None) -> Digest:
        digest_date = digest_date or date.today()
        default_lang = Language.default()
        if not default_lang:
            raise RuntimeError("No default language set. Run initdigest first.")

        if languages:
            target_langs = list(Language.objects.filter(code__in=languages).exclude(pk=default_lang.pk))
        else:
            target_langs = list(Language.objects.exclude(pk=default_lang.pk))

        # Fresh run
        Digest.objects.filter(date=digest_date).delete()
        digest = Digest.objects.create(date=digest_date)

        # Collect
        section_articles = self.collector.collect()
        total = sum(len(a) for _, a in section_articles)
        if total == 0:
            raise RuntimeError("No articles found. Check embeddings and sections.")

        # Process each section sequentially
        for section, articles in section_articles:
            try:
                stories, usage = self.analyzer.analyze(section, articles)
                record_digest_usage(usage, step=APIUsage.Step.ANALYZE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest)
            except Exception:
                logger.exception("Analysis failed for [%s]", section.slug)
                continue

            for story in stories:
                try:
                    self._process_story(digest, section, story, default_lang)
                except Exception:
                    logger.exception("Story '%s' failed, skipping", story.get("label", "?"))

        if not digest.items.exists():
            raise RuntimeError("No items generated.")

        # Headline
        items_data = [
            {"topic": t.topic, "importance": item.importance}
            for item in digest.items.prefetch_related("translations").all()
            for t in item.translations.all()
            if t.language_id == default_lang.pk
        ]
        headline, usage = self.headline_generator.generate(items_data)
        record_digest_usage(usage, step=APIUsage.Step.HEADLINE,
                            api_type=APIUsage.APIType.CHAT,
                            model=self.config.chat_model, digest=digest)
        DigestTranslation.objects.create(digest=digest, language=default_lang, headline=headline)

        digest.stage = Digest.Stage.SAVED
        digest.save(update_fields=["stage"])

        # Translate
        if target_langs:
            self._translate_all(digest, default_lang, target_langs)

        digest.stage = Digest.Stage.DONE
        digest.save(update_fields=["stage"])

        logger.info("Digest %s complete: %d items", digest.date, digest.items.count())
        return digest

    def _process_story(self, digest, section, story, default_lang):
        """Process one story: refine -> generate -> save as DigestItem."""
        refined, refine_usage = self.refiner.refine(story, {})
        if not refined:
            return

        item_data, gen_usage = self.item_generator.generate(story, refined)

        item = self.saver.save_item(digest, section, story, item_data, refined, default_lang)

        # Record per-step usage with item link
        record_digest_usage(refine_usage, step=APIUsage.Step.REFINE,
                            api_type=APIUsage.APIType.EMBEDDING,
                            model=EMBEDDING_MODEL, digest=digest, item=item)
        record_digest_usage(gen_usage, step=APIUsage.Step.GENERATE,
                            api_type=APIUsage.APIType.CHAT,
                            model=self.config.chat_model, digest=digest, item=item)

    def _translate_all(self, digest, default_lang, target_langs):
        """Translate all items and headline to target languages."""
        items = list(digest.items.prefetch_related("translations").all())
        item_texts = []
        for item in items:
            for t in item.translations.all():
                if t.language_id == default_lang.pk:
                    item_texts.append((item, t.topic, t.summary))
                    break

        headline_en = digest.get_headline(default_lang)

        for lang in target_langs:
            try:
                translated_headline, h_usage = self.translator.translate_headline(headline_en, lang.name)
                record_digest_usage(h_usage, step=APIUsage.Step.TRANSLATE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest)
            except Exception:
                logger.exception("Headline translation to %s failed", lang.code)
                translated_headline = ""

            item_translations = []
            for item, topic, summary in item_texts:
                try:
                    translated, usage = self.translator.translate_item(topic, summary, lang.name)
                    item_translations.append((item, translated))
                    record_digest_usage(usage, step=APIUsage.Step.TRANSLATE,
                                        api_type=APIUsage.APIType.CHAT,
                                        model=self.config.chat_model, digest=digest, item=item)
                except Exception:
                    logger.exception("Translation to %s failed for item #%s", lang.code, item.pk)

            self.saver.save_translations(digest, lang, item_translations, translated_headline)

            # Batch update translated_at
            translated_item_ids = [item.pk for item, _ in item_translations]
            if translated_item_ids:
                ItemPipeline.objects.filter(
                    item_id__in=translated_item_ids, translated_at__isnull=True,
                ).update(translated_at=timezone.now())

            logger.info("Translated to %s: %d items", lang.code, len(item_translations))
