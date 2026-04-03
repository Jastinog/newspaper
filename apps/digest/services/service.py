import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from django.db import close_old_connections

from apps.billing.models import APIUsage
from apps.billing.services import record_digest_usage
from apps.core.models import Language
from apps.core.services.ai import (
    EMBEDDING_MODEL, OpenAIClient, EmbeddingClient,
)
from apps.digest.models import (
    ArticleUse, Digest, DigestConfig, DigestItemTranslation, DigestTranslation,
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
    """Digest pipeline: collect → analyze → generate items (each immediately visible).

    1. Collect articles per section (embedding search)
    2. Analyze each section → identify stories, deduplicate
    3. For each story: refine → generate (all languages) → save → assign image → VISIBLE
    4. Generate headline
    """

    def __init__(self, config: DigestConfig = None):
        self.config = config or DigestConfig.get()
        self.client = OpenAIClient()
        self.embedder = EmbeddingClient()
        self.collector = SectionArticleCollector(config=self.config)
        self.analyzer = StoryAnalyzer(client=self.client, config=self.config)
        self.refiner = StoryRefiner(embedder=self.embedder, config=self.config)
        self.generator = ItemGenerator(client=self.client, config=self.config)
        self.headline_generator = HeadlineGenerator(client=self.client, config=self.config)
        self.translator = ItemTranslator(client=self.client, config=self.config)
        self.deduplicator = StoryDeduplicator(embedder=self.embedder)
        self.saver = DigestSaver()

    def run(self, digest_date: date = None, languages: list[str] = None) -> Digest:
        digest_date = digest_date or date.today()
        default_lang = Language.default()
        if not default_lang:
            raise RuntimeError("No default language set. Run initdigest first.")

        target_langs = list(
            Language.active_targets().filter(code__in=languages) if languages
            else Language.active_targets()
        )

        Digest.objects.filter(date=digest_date).delete()
        digest = Digest.objects.create(date=digest_date)

        # ── 1. Collect candidates (fast) ──
        section_articles = self.collector.collect()
        if not any(articles for _, articles in section_articles):
            raise RuntimeError("No articles found. Check embeddings and sections.")

        # ── 2. Analyze → stories → deduplicate ──
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

        section_stories = self.deduplicator.deduplicate(section_stories)

        # ── 3. Generate items — each one immediately display-ready ──
        item_count = self._generate_items(digest, section_stories, default_lang,
                                          target_langs)
        if item_count == 0:
            raise RuntimeError("No items generated.")

        # ── 4. Headline ──
        self._generate_headline(digest, default_lang, target_langs)

        digest.stage = Digest.Stage.DONE
        digest.save(update_fields=["stage"])
        logger.info("Digest %s complete: %d items", digest.date, item_count)
        return digest

    # ── Item generation ──────────────────────────────────────────

    def _generate_items(self, digest, section_stories, default_lang,
                        target_langs) -> int:
        """Generate all items. Each is saved with translations + image immediately.

        Sections are processed sequentially (for article dedup).
        Stories within a section run in parallel.
        Image assignment happens in the main thread as each story completes.
        """
        used_ids = set(ArticleUse.objects.values_list("article_id", flat=True))
        used_image_ids = set()
        item_count = 0

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            for section, stories in section_stories:
                futures = {
                    pool.submit(
                        self._refine_and_generate, digest, section, story,
                        default_lang, target_langs, used_ids,
                    ): story
                    for story in stories
                }

                for future in as_completed(futures):
                    result = future.result()
                    if not result:
                        continue

                    item, common_data = result
                    article_ids = common_data.get("article_ids", [])

                    # Image assignment in main thread (thread-safe)
                    image_id = self.saver.assign_image(item, used_image_ids, article_ids)
                    if image_id:
                        used_image_ids.add(image_id)

                    used_ids.update(article_ids)
                    item_count += 1

                    if digest.stage < Digest.Stage.GENERATED:
                        digest.stage = Digest.Stage.GENERATED
                        digest.save(update_fields=["stage"])

        return item_count

    def _refine_and_generate(self, digest, section, story, default_lang,
                             target_langs, used_ids):
        """Worker: refine → generate → save (text + translations). Returns (item, common_data)."""
        close_old_connections()
        try:
            refined, refine_usage = self.refiner.refine(story, used_ids=used_ids)
            if not refined:
                return None

            all_langs = [(default_lang.code, default_lang.name)]
            all_langs.extend((l.code, l.name) for l in target_langs)

            by_lang, common_data, gen_usage = self.generator.generate(
                story, refined, languages=all_langs,
            )

            item = self.saver.save_item(
                digest, section, story, by_lang, common_data,
                refined, default_lang, target_langs,
            )

            record_digest_usage(refine_usage, step=APIUsage.Step.REFINE,
                                api_type=APIUsage.APIType.EMBEDDING,
                                model=EMBEDDING_MODEL, digest=digest, item=item)
            record_digest_usage(gen_usage, step=APIUsage.Step.GENERATE,
                                api_type=APIUsage.APIType.CHAT,
                                model=self.config.chat_model, digest=digest, item=item)

            return item, common_data
        except Exception:
            logger.exception("Story '%s' failed", story.get("label", "?"))
            return None
        finally:
            close_old_connections()

    # ── Headline ─────────────────────────────────────────────────

    def _generate_headline(self, digest, default_lang, target_langs):
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

        for lang in target_langs:
            try:
                translated, h_usage = self.translator.translate_headline(headline, lang.name)
                record_digest_usage(h_usage, step=APIUsage.Step.TRANSLATE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest)
                self.saver.save_translations(digest, lang, [], translated)
            except Exception:
                logger.exception("Headline translation to %s failed", lang.code)
