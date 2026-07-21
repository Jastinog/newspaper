"""Assign an article to its best-matching DigestSection by embedding similarity.

The day-less replacement for the old daily digest: instead of a batch run per
calendar day, each article is matched — right after it is embedded — to the one
section whose seed phrases it resembles most (argmax over cosine similarity).
Same math as the retired `EmbeddingEdition._assign`, now per-article.
"""

import logging
import threading
from collections import defaultdict

import numpy as np

from apps.digest.models import DigestConfig, SectionEmbedding
from apps.feed.models import Article, ArticleChunk

logger = logging.getLogger(__name__)

# Section seed vectors change only when the operator re-seeds (via `initdigest`),
# so the matrix is cached for the process lifetime. Call `reload_sections()`
# after editing seeds — or restart the worker — to pick up changes.
_lock = threading.Lock()
_cache: dict = {"section_ids": None, "S": None}


def reload_sections() -> None:
    """Drop the cached seed matrix so the next assignment reloads it."""
    with _lock:
        _cache["section_ids"] = None
        _cache["S"] = None


def _load_sections():
    """Return (list[section_id] per seed row, matrix (n_seeds, dim)), cached."""
    with _lock:
        if _cache["S"] is None:
            rows = list(
                SectionEmbedding.objects
                .filter(section__enabled=True)
                .values_list("section_id", "embedding")
            )
            if rows:
                _cache["section_ids"] = [r[0] for r in rows]
                _cache["S"] = np.asarray([r[1] for r in rows], dtype=np.float32)
        return _cache["section_ids"], _cache["S"]


def assign_section(article_id: int, title: str = "", content: str = "") -> int:
    """Match one article to its best section (argmax over section seed vectors).

    Sets `article.section` + `section_score` when the best cosine score clears
    `DigestConfig.embed_score_floor`; otherwise leaves them unset. Returns 1 if a
    section was assigned, else 0. `title`/`content` are unused (the enrichment
    stage passes them uniformly) — matching runs off the article's chunk vectors.
    The caller flags the article `sectioned=True` regardless, so a no-match
    article isn't retried forever.
    """
    seed_section_ids, S = _load_sections()
    if S is None:
        logger.warning("No section embeddings; run initdigest. Skipping %s", article_id)
        return 0

    rows = list(
        ArticleChunk.objects.filter(article_id=article_id).values_list("embedding", flat=True)
    )
    if not rows:
        return 0
    C = np.asarray(rows, dtype=np.float32)  # (n_chunks, dim)

    # Vectors are L2-normalized, so C @ S.T is cosine similarity.
    sims = C @ S.T  # (n_chunks, n_seeds)

    # An article's score for a section = its best chunk against that section's
    # best seed (max over both the chunk rows and the section's seed columns).
    cols_by_section = defaultdict(list)
    for col, sid in enumerate(seed_section_ids):
        cols_by_section[sid].append(col)
    section_ids = sorted(cols_by_section)
    per_section = np.array([
        sims[:, cols_by_section[sid]].max() for sid in section_ids
    ])

    best = int(per_section.argmax())
    best_score = float(per_section[best])
    if best_score < DigestConfig.get().embed_score_floor:
        return 0

    Article.objects.filter(id=article_id).update(
        section_id=section_ids[best], section_score=best_score,
    )
    return 1
