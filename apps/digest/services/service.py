import logging
from datetime import date

from apps.billing.models import APIUsage
from apps.billing.services import record_digest_usage
from apps.core.models import Language
from apps.core.services.ai import (
    EMBEDDING_MODEL, OpenAIClient, EmbeddingClient,
)
from apps.digest.models import ArticleUse, Digest, DigestConfig

from .analyzer import StoryAnalyzer
from .collector import SectionArticleCollector
from .deduplicator import StoryDeduplicator
from .generator import ItemGenerator
from .refiner import StoryRefiner
from .saver import DigestSaver


logger = logging.getLogger(__name__)

class DigestService:
    """Digest pipeline: collect → analyze → generate items (each immediately visible).

    1. Collect articles per section (embedding search)
    2. Analyze each section → identify stories, deduplicate
    3. For each story: refine → generate (all languages) → save → assign image → VISIBLE
    """

    def __init__(self, config: DigestConfig = None):
        self.config = config or DigestConfig.get()
        self.client = OpenAIClient()
        self.embedder = EmbeddingClient()
        self.collector = SectionArticleCollector(config=self.config)
        self.analyzer = StoryAnalyzer(client=self.client, config=self.config)
        self.refiner = StoryRefiner(embedder=self.embedder, config=self.config)
        self.generator = ItemGenerator(client=self.client, config=self.config)
        self.deduplicator = StoryDeduplicator(embedder=self.embedder)
        self.saver = DigestSaver()

    def run(self, digest_date: date = None, languages: list[str] = None,
            on_event=None) -> Digest:
        """Run the full digest pipeline.

        Args:
            on_event: optional callback(event, **kwargs) for progress reporting.
                Events: 'collect', 'analyze_section', 'analyze_done',
                        'generate_start', 'generate_item', 'generate_skip', 'done'
        """
        emit = on_event or (lambda *a, **kw: None)
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

        # 1. Collect
        section_articles = self.collector.collect()
        total_articles = sum(len(a) for _, a in section_articles)
        if total_articles == 0:
            raise RuntimeError("No articles found. Check embeddings and sections.")
        emit("collect", sections=len(section_articles), articles=total_articles)

        # 2. Analyze + deduplicate
        section_stories = []
        for section, articles in section_articles:
            try:
                stories, usage = self.analyzer.analyze(section, articles)
                record_digest_usage(usage, step=APIUsage.Step.ANALYZE,
                                    api_type=APIUsage.APIType.CHAT,
                                    model=self.config.chat_model, digest=digest)
                if stories:
                    section_stories.append((section, stories))
                    emit("analyze_section", section=section.slug,
                         articles=len(articles), stories=len(stories))
            except Exception:
                logger.exception("Analysis failed for [%s]", section.slug)
                emit("analyze_section", section=section.slug,
                     articles=len(articles), stories=0, error=True)

        section_stories = self.deduplicator.deduplicate(section_stories)
        total_stories = sum(len(s) for _, s in section_stories)
        emit("analyze_done", sections=len(section_stories), stories=total_stories)

        # 3. Generate
        emit("generate_start", stories=total_stories)
        item_count = self._generate_items(digest, section_stories, default_lang,
                                          target_langs, emit)
        if item_count == 0:
            raise RuntimeError("No items generated.")

        digest.stage = Digest.Stage.DONE
        digest.save(update_fields=["stage"])
        emit("done", items=item_count)
        logger.info("Digest %s complete: %d items", digest.date, item_count)
        return digest

    # ── Item generation ──────────────────────────────────────────

    def _generate_items(self, digest, section_stories, default_lang,
                        target_langs, emit) -> int:
        """Generate all items sequentially. Each is saved and visible immediately."""
        used_ids = set(ArticleUse.objects.values_list("article_id", flat=True))
        used_image_ids = set()
        item_count = 0
        story_index = 0

        for section, stories in section_stories:
            for story in stories:
                story_index += 1
                label = story.get("label", "?")
                try:
                    item = self._refine_and_generate(
                        digest, section, story,
                        default_lang, target_langs, used_ids, used_image_ids,
                    )
                except Exception:
                    logger.exception("Story '%s' failed", label)
                    emit("generate_skip", index=story_index, label=label, reason="error")
                    continue

                if not item:
                    emit("generate_skip", index=story_index, label=label, reason="empty")
                    continue

                item_count += 1
                emit("generate_item", index=story_index, label=label,
                     section=section.slug, item_count=item_count)

        if item_count and digest.stage < Digest.Stage.GENERATED:
            digest.stage = Digest.Stage.GENERATED
            digest.save(update_fields=["stage"])

        return item_count

    def _refine_and_generate(self, digest, section, story,
                             default_lang, target_langs, used_ids, used_image_ids):
        """Refine → generate → validate → save → assign image. Returns item or None."""
        refined, refine_usage = self.refiner.refine(story, used_ids=used_ids)
        if not refined:
            return None

        all_langs = [(default_lang.code, default_lang.name)]
        all_langs.extend((lang.code, lang.name) for lang in target_langs)

        by_lang, common_data, gen_usage = self.generator.generate(
            story, refined, languages=all_langs,
        )

        # Validate: default language must have topic and summary
        default_data = by_lang.get(default_lang.code, {})
        if not default_data.get("topic") or not default_data.get("summary"):
            logger.warning("Empty generation for '%s', skipping", story.get("label", "?"))
            return None

        article_ids = [a["id"] for a in refined]
        common_data["article_ids"] = article_ids

        item = self.saver.save_item(
            digest, section, story, by_lang, common_data,
            refined, default_lang, target_langs,
        )

        image_id = self.saver.assign_image(item, used_image_ids, article_ids)
        if image_id:
            used_image_ids.add(image_id)
        used_ids.update(article_ids)

        record_digest_usage(refine_usage, step=APIUsage.Step.REFINE,
                            api_type=APIUsage.APIType.EMBEDDING,
                            model=EMBEDDING_MODEL, digest=digest, item=item)
        record_digest_usage(gen_usage, step=APIUsage.Step.GENERATE,
                            api_type=APIUsage.APIType.CHAT,
                            model=self.config.chat_model, digest=digest, item=item)

        return item

