"""Embedding-based digest generation — no OpenAI.

Each digest section ships a set of descriptive seed phrases (embedded once by
`initdigest` into `SectionEmbedding`). This service matches recent article
chunks against those seeds with a single local cosine matmul, assigns every
article to the *one* section it matches best (argmax), and stores the top
matches per section as `DigestItem`s. Items carry no generated topic/summary —
the display falls back to each article's own title and teaser
(`DigestItem.get_topic`/`get_summary`).
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from django.utils import timezone

from apps.digest.models import (
    Digest, DigestConfig, DigestItem, DigestSection, SectionEmbedding,
)
from apps.feed.models import Article, ArticleChunk

from .saver import DigestSaver

logger = logging.getLogger(__name__)


class EmbeddingEdition:
    """Local, embedding-only digest pipeline: collect -> match -> save."""

    def __init__(self, config: DigestConfig = None):
        self.config = config or DigestConfig.get()
        self.saver = DigestSaver()

    def run(self, digest_date: date = None, per_section: int = None,
            on_event=None) -> Digest:
        emit = on_event or (lambda *a, **kw: None)
        cfg = self.config
        digest_date = digest_date or date.today()
        per_section = per_section or cfg.edition_items_per_section
        floor = cfg.embed_score_floor

        # ── Section seed vectors ────────────────────────────────
        seed_section_ids, S = self._load_section_vectors()
        if S is None:
            raise RuntimeError("No section embeddings. Run initdigest first.")

        # ── Step 1: Collect candidate articles + their chunks ───
        chunk_article_ids, C = self._collect(cfg)
        if C is None:
            raise RuntimeError("No embedded articles in the lookback window.")
        emit("collect", articles=int(np.unique(chunk_article_ids).size),
             chunks=int(C.shape[0]))

        # ── Step 2: Score & assign (argmax) ─────────────────────
        assignments = self._assign(chunk_article_ids, C, seed_section_ids, S, floor)
        if not assignments:
            raise RuntimeError("No article cleared the score floor.")

        # ── Step 3: Save ────────────────────────────────────────
        Digest.objects.filter(date=digest_date).delete()
        digest = Digest.objects.create(date=digest_date)

        total_items = self._save_items(digest, assignments, per_section, emit)
        if total_items == 0:
            raise RuntimeError("No items produced.")

        digest.stage = Digest.Stage.DONE
        digest.save(update_fields=["stage"])
        self.saver.invalidate_index_cache()

        emit("done", items=total_items, sections=len(assignments))
        logger.info("Embedding edition %s: %d items across %d sections",
                     digest.date, total_items, len(assignments))
        return digest

    # ── Step 3: Save ────────────────────────────────────────────

    def _save_items(self, digest, assignments, per_section, emit) -> int:
        """Persist the ranked assignments as DigestItems in a handful of bulk
        queries (each item links exactly one article, so the per-item
        create + link_articles path would be a needless N+1)."""
        # Sections are already enabled-filtered upstream (_load_section_vectors).
        sections = {
            s.id: s for s in DigestSection.objects.filter(id__in=assignments.keys())
        }

        # Flatten to (section, article_id, score, order), capped per section.
        entries = []
        for sec_id, ranked in assignments.items():
            section = sections.get(sec_id)
            if not section:
                continue
            ranked = ranked[:per_section]
            for order, (article_id, score) in enumerate(ranked):
                entries.append((section, article_id, score, order))
            emit("section", slug=section.slug, count=len(ranked))

        if not entries:
            return 0

        # freshness = newest published timestamp of the linked article (one query).
        article_ids = [aid for _, aid, _, _ in entries]
        published = dict(
            Article.objects
            .filter(id__in=article_ids, published__isnull=False)
            .values_list("id", "published")
        )

        items = [
            DigestItem(
                digest=digest, section=section, match_score=score, order=order,
                freshness=published[aid].timestamp() if aid in published else 0,
            )
            for section, aid, score, order in entries
        ]
        DigestItem.objects.bulk_create(items)

        Through = DigestItem.articles.through
        Through.objects.bulk_create([
            Through(digestitem_id=item.pk, article_id=aid)
            for item, (_, aid, _, _) in zip(items, entries)
        ])
        Article.objects.filter(id__in=article_ids).update(used_in_digest=True)

        return len(items)

    # ── Section vectors ─────────────────────────────────────────

    def _load_section_vectors(self):
        """Return (list[section_id] per seed, matrix (M, dim)) for enabled
        sections, or (None, None) if there are no seeds."""
        rows = list(
            SectionEmbedding.objects
            .filter(section__enabled=True)
            .values_list("section_id", "embedding")
        )
        if not rows:
            return None, None
        section_ids = [r[0] for r in rows]
        S = np.asarray([r[1] for r in rows], dtype=np.float32)
        return section_ids, S

    # ── Step 1: Collect ─────────────────────────────────────────

    def _collect(self, cfg):
        """Load candidate article chunk vectors.

        Candidate articles mirror the legacy collector's filters: completed,
        from an enabled feed, with content and an image, not yet used in a
        digest, published within the lookback window."""
        now = timezone.now()
        cutoff = now - timedelta(hours=cfg.hours_lookback)

        candidate_ids = list(
            Article.objects
            .filter(
                published__gte=cutoff,
                published__lte=now,
                feed__enabled=True,
                status=Article.Status.COMPLETED,
                used_in_digest=False,
            )
            .exclude(content="")
            .exclude(image="")
            .values_list("id", flat=True)
        )
        if not candidate_ids:
            return np.empty(0, dtype=np.int64), None

        rows = list(
            ArticleChunk.objects
            .filter(article_id__in=candidate_ids)
            .values_list("article_id", "embedding")
        )
        if not rows:
            return np.empty(0, dtype=np.int64), None

        chunk_article_ids = np.asarray([r[0] for r in rows], dtype=np.int64)
        C = np.asarray([r[1] for r in rows], dtype=np.float32)
        return chunk_article_ids, C

    # ── Step 2: Score & assign ──────────────────────────────────

    def _assign(self, chunk_article_ids, C, seed_section_ids, S, floor):
        """Assign each article to its single best-scoring section.

        Returns {section_id: [(article_id, score), ...]} sorted by score desc.
        Vectors are L2-normalized, so C @ S.T is cosine similarity."""
        sims = C @ S.T  # (n_chunks, n_seeds)

        # Collapse seeds -> sections: max over each section's seed columns.
        cols_by_section = defaultdict(list)
        for col, sid in enumerate(seed_section_ids):
            cols_by_section[sid].append(col)
        section_ids = sorted(cols_by_section)
        chunk_sec = np.column_stack([
            sims[:, cols_by_section[sid]].max(axis=1) for sid in section_ids
        ])  # (n_chunks, n_sections)

        # Collapse chunks -> articles: max over each article's chunks.
        assignments: dict[int, list] = {}
        for aid in np.unique(chunk_article_ids):
            mask = chunk_article_ids == aid
            art_scores = chunk_sec[mask].max(axis=0)  # (n_sections,)
            best_col = int(art_scores.argmax())
            best_score = float(art_scores[best_col])
            if best_score < floor:
                continue
            sec_id = section_ids[best_col]
            assignments.setdefault(sec_id, []).append((int(aid), best_score))

        for sec_id in assignments:
            assignments[sec_id].sort(key=lambda t: t[1], reverse=True)
        return assignments
