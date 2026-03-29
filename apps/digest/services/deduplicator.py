import logging
import math

from apps.core.services.ai import EmbeddingClient

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.85


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


class StoryDeduplicator:
    """Deduplicates stories across sections using embedding similarity."""

    def __init__(self, embedder: EmbeddingClient = None):
        self.embedder = embedder or EmbeddingClient()

    def deduplicate(self, section_stories: list[tuple]) -> list[tuple]:
        """Remove duplicate stories across sections.

        Args:
            section_stories: [(section, [story_dict, ...]), ...]

        Returns:
            Same structure with cross-section duplicates removed.
        """
        entries = []
        for sec_i, (section, stories) in enumerate(section_stories):
            for st_i, story in enumerate(stories):
                entries.append((sec_i, st_i, story.get("label", "")))

        if len(entries) < 2:
            return section_stories

        labels = [e[2] for e in entries]

        try:
            vectors, _ = self.embedder.embed_batch(labels)
        except Exception as e:
            logger.warning("Dedup embedding failed, skipping: %s", e)
            return section_stories

        if not vectors:
            return section_stories

        removed = set()
        for i in range(len(entries)):
            if i in removed:
                continue
            for j in range(i + 1, len(entries)):
                if j in removed:
                    continue
                if entries[i][0] == entries[j][0]:
                    continue
                similarity = _cosine_similarity(vectors[i], vectors[j])
                if similarity >= DEDUP_THRESHOLD:
                    story_i = section_stories[entries[i][0]][1][entries[i][1]]
                    story_j = section_stories[entries[j][0]][1][entries[j][1]]
                    ids_i = len(story_i.get("article_ids", []))
                    ids_j = len(story_j.get("article_ids", []))

                    if ids_i >= ids_j:
                        winner, loser, loser_idx = story_i, story_j, j
                    else:
                        winner, loser, loser_idx = story_j, story_i, i

                    winner["article_ids"] = list(set(
                        winner.get("article_ids", []) + loser.get("article_ids", [])
                    ))
                    winner["search_queries"] = list(set(
                        winner.get("search_queries", []) + loser.get("search_queries", [])
                    ))

                    removed.add(loser_idx)
                    logger.info("Dedup: merged '%s' into '%s' (sim=%.2f)",
                                loser.get("label"), winner.get("label"), similarity)

        if not removed:
            return section_stories

        removed_by_section = {}
        for idx in removed:
            sec_i, st_i, _ = entries[idx]
            removed_by_section.setdefault(sec_i, set()).add(st_i)

        result = []
        for sec_i, (section, stories) in enumerate(section_stories):
            to_remove = removed_by_section.get(sec_i, set())
            filtered = [s for i, s in enumerate(stories) if i not in to_remove]
            result.append((section, filtered))

        logger.info("Dedup: removed %d duplicate stories across sections", len(removed))
        return result
