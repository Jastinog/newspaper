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

    Per item: collect -> analyze -> refine -> generate -> translate.
    Headline generated and translated after all items.
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
            target_langs = list(
                Language.active_targets().filter(code__in=languages)
            )
        else:
            target_langs = list(Language.active_targets())

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
                    self._process_story(digest, section, story, default_lang, target_langs)
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

        # Translate headline to target languages
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

    def _process_story(self, digest, section, story, default_lang, target_langs):
        """Process one story: refine -> generate -> translate -> save."""
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

        # Translate item to all active languages immediately
        topic = item_data.get("topic", "")
        summary = item_data.get("summary", "")

        for lang in target_langs:
            try:
                translated, usage = self.translator.translate_item(topic, summary, lang.name)
                self.saver.save_translations(digest, lang, [(item, translated)], "")
                record_digest_usage(usage, step=APIUsage.Step.TRANSLATE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest, item=item)
            except Exception:
                logger.exception("Translation to %s failed for item #%s", lang.code, item.pk)

        if target_langs:
            ItemPipeline.objects.filter(
                item=item, translated_at__isnull=True,
            ).update(translated_at=timezone.now())
