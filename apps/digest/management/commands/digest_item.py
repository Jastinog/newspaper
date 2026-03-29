"""
Prototype: generate digest items for one or all sections.

Usage:
    python manage.py digest_item --section world-politics
    python manage.py digest_item --section technology --items 3
    python manage.py digest_item --all --items 2
    python manage.py digest_item --all --items 2 --translate
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing.models import APIUsage
from apps.billing.services import record_digest_usage
from apps.core.models import Language
from apps.core.services.ai import (
    EMBEDDING_MODEL, OpenAIClient, EmbeddingClient, calculate_cost,
)
from apps.digest.models import (
    Digest, DigestConfig, DigestItemTranslation,
    DigestSection, ItemPipeline,
)
from apps.digest.services.analyzer import StoryAnalyzer
from apps.digest.services.collector import SectionArticleCollector
from apps.digest.services.generator import ItemGenerator
from apps.digest.services.refiner import StoryRefiner
from apps.digest.services.saver import DigestSaver
from apps.digest.services.translator import ItemTranslator


class Command(BaseCommand):
    help = "Generate digest items for one or all sections (prototype for testing algorithm & costs)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--section", type=str, help="Section slug (e.g. world-politics)")
        group.add_argument("--all", action="store_true", help="Process all enabled sections")
        parser.add_argument("--items", type=int, default=1, help="Items per section (default: 1)")
        parser.add_argument("--date", type=str, default=None, help="Digest date YYYY-MM-DD (default: today)")
        parser.add_argument("--translate", action="store_true", help="Also translate to all languages")

    def handle(self, *args, **options):
        config = DigestConfig.get()
        default_lang = Language.default()
        if not default_lang:
            self.stderr.write(self.style.ERROR("No default language. Run initdigest first."))
            return

        # Resolve sections
        if options["all"]:
            sections = list(DigestSection.objects.filter(enabled=True).prefetch_related("embeddings"))
            if not sections:
                self.stderr.write(self.style.ERROR("No enabled sections."))
                return
        else:
            try:
                sections = [DigestSection.objects.prefetch_related("embeddings").get(slug=options["section"])]
            except DigestSection.DoesNotExist:
                slugs = list(DigestSection.objects.values_list("slug", flat=True))
                self.stderr.write(self.style.ERROR(
                    f"Section '{options['section']}' not found. Available: {slugs}"
                ))
                return

        digest_date = date.today()
        if options["date"]:
            digest_date = datetime.strptime(options["date"], "%Y-%m-%d").date()

        digest, _ = Digest.objects.get_or_create(date=digest_date)

        # Shared clients (created once, reused across sections)
        client = OpenAIClient()
        embedder = EmbeddingClient()

        all_costs = []
        all_items = []

        for section in sections:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n{'=' * 60}\n  Section: {section.slug}\n{'=' * 60}"
            ))
            items, costs = self._process_section(
                section, digest, config, default_lang, options, client, embedder,
            )
            all_items.extend(items)
            all_costs.extend(costs)

        if not all_items:
            self.stderr.write(self.style.WARNING("\nNo items generated."))
            return

        self._print_costs(all_costs, len(all_items))
        ids = ", #".join(str(i.pk) for i in all_items)
        self.stdout.write(self.style.SUCCESS(
            f"\nDone! {len(all_items)} items across {len(sections)} section(s): #{ids}"
        ))

    # ── Per-section pipeline ─────────────────────────────────────

    def _process_section(self, section, digest, config, default_lang, options,
                         client, embedder):
        max_items = options["items"]
        costs = []
        saver = DigestSaver()

        # 1. Collect
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n1. Collecting articles"))
        collector = SectionArticleCollector(config=config)
        articles = collector.collect_section(section)
        self.stdout.write(f"   {len(articles)} articles found")

        if not articles:
            self.stderr.write(self.style.WARNING("   No articles. Check embeddings."))
            return [], []

        for a in articles[:5]:
            self.stdout.write(f"   - [{a['id']}] {a['title'][:70]}")
        if len(articles) > 5:
            self.stdout.write(f"   ... and {len(articles) - 5} more")

        # 2. Analyze
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Analyzing stories (LLM)"))
        analyzer = StoryAnalyzer(client=client, config=config)
        stories, analyze_usage = analyzer.analyze(section, articles)
        costs.append(("analyze", analyze_usage, config.chat_model))
        self.stdout.write(f"   {analyze_usage.get('total_tokens', 0):,} tokens, {len(stories)} stories")

        if not stories:
            self.stderr.write(self.style.WARNING("   No stories identified."))
            return [], costs

        # Record analyze usage once (section-level, not per-item)
        record_digest_usage(analyze_usage, step=APIUsage.Step.ANALYZE,
                            api_type=APIUsage.APIType.CHAT,
                            model=config.chat_model, digest=digest)

        to_process = stories[:max_items]
        for i, s in enumerate(stories):
            marker = " <--" if i < max_items else ""
            self.stdout.write(
                f"   {i}. {s['label']} "
                f"({len(s.get('article_ids', []))} articles){marker}"
            )

        # 3-5. Refine + Generate + Save per story
        refiner = StoryRefiner(embedder=embedder, config=config)
        generator = ItemGenerator(client=client, config=config)
        saved = []

        for idx, story in enumerate(to_process):
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n--- [{idx + 1}/{len(to_process)}] {story['label']} ---"
            ))

            # Refine
            refined, refine_usage = refiner.refine(story)
            costs.append(("refine", refine_usage, EMBEDDING_MODEL))
            self.stdout.write(
                f"   Refine: {len(story.get('article_ids', []))} -> {len(refined)} articles"
            )
            if not refined:
                self.stderr.write(self.style.WARNING("   No articles, skipping"))
                continue

            # Generate
            item_data, gen_usage = generator.generate(story, refined)
            costs.append(("generate", gen_usage, config.chat_model))

            self.stdout.write(f"   Generate: {gen_usage.get('total_tokens', 0):,} tokens")
            self.stdout.write(f"   Topic:      {item_data.get('topic', '')}")
            self.stdout.write(f"   Importance: {item_data.get('importance', 0)}")
            self.stdout.write(f"   Summary:    {item_data.get('summary', '')[:150]}...")

            # Save (shared logic)
            item = saver.save_item(digest, section, story, item_data, refined, default_lang)

            # APIUsage per step
            record_digest_usage(refine_usage, step=APIUsage.Step.REFINE,
                                api_type=APIUsage.APIType.EMBEDDING,
                                model=EMBEDDING_MODEL, digest=digest, item=item)
            record_digest_usage(gen_usage, step=APIUsage.Step.GENERATE,
                                api_type=APIUsage.APIType.CHAT,
                                model=config.chat_model, digest=digest, item=item)

            saved.append(item)
            self.stdout.write(f"   Saved: DigestItem #{item.pk} ({item.articles.count()} articles)")

        # Translate (optional)
        if options["translate"] and saved:
            target_langs = list(Language.active_targets())
            if target_langs:
                self.stdout.write(self.style.MIGRATE_HEADING("\nTranslating"))
                translator = ItemTranslator(client=client, config=config)
                for item in saved:
                    t_en = item.translations.filter(language=default_lang).first()
                    if not t_en:
                        continue
                    for lang in target_langs:
                        try:
                            translated, t_usage = translator.translate_item(
                                t_en.topic, t_en.summary, lang.name,
                            )
                            costs.append(("translate", t_usage, config.chat_model))
                            DigestItemTranslation.objects.update_or_create(
                                item=item, language=lang,
                                defaults={
                                    "topic": translated.get("topic", ""),
                                    "summary": translated.get("summary", ""),
                                },
                            )
                            record_digest_usage(t_usage, step=APIUsage.Step.TRANSLATE,
                                                api_type=APIUsage.APIType.CHAT,
                                                model=config.chat_model, digest=digest, item=item)
                            self.stdout.write(
                                f"   #{item.pk} -> {lang.code}: {translated.get('topic', '')}"
                            )
                        except Exception as e:
                            self.stderr.write(f"   #{item.pk} -> {lang.code}: FAILED ({e})")

                # Batch update translated_at
                translated_ids = [item.pk for item in saved]
                ItemPipeline.objects.filter(
                    item_id__in=translated_ids, translated_at__isnull=True,
                ).update(translated_at=timezone.now())

        return saved, costs

    # ── Helpers ───────────────────────────────────────────────────

    def _print_costs(self, costs, item_count):
        self.stdout.write(self.style.MIGRATE_HEADING("\nCost breakdown"))
        totals = {}
        grand_tokens = 0
        grand_cost = 0
        for step_name, usage, model in costs:
            tokens = usage.get("total_tokens", 0)
            cost = calculate_cost(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            grand_tokens += tokens
            grand_cost += cost
            if step_name not in totals:
                totals[step_name] = {"tokens": 0, "cost": 0, "model": model}
            totals[step_name]["tokens"] += tokens
            totals[step_name]["cost"] += cost

        for name, d in totals.items():
            self.stdout.write(f"   {name:12} {d['tokens']:>7,} tokens  ${d['cost']:.6f}  ({d['model']})")
        self.stdout.write(f"   {'TOTAL':12} {grand_tokens:>7,} tokens  ${grand_cost:.6f}")
        if item_count > 0:
            self.stdout.write(
                f"   {'PER ITEM':12} {grand_tokens // item_count:>7,} tokens  "
                f"${grand_cost / item_count:.6f}"
            )
