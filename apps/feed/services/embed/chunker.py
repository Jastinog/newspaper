"""Split an article into overlapping text chunks for embedding.

News bodies are short, so a handful of ~paragraph-sized chunks captures the
whole article well within BGE's 512-token window. The title is prepended to the
first chunk so a title-only match still lands somewhere. Chunking happens on
paragraph then sentence boundaries, never mid-word.
"""

import re

# Target chunk size in characters. English averages ~4 chars/token, so ~1200
# chars stays comfortably under BGE's 512-token limit even after tokenization.
CHUNK_CHARS = 1200
OVERLAP_CHARS = 150
# Never emit more than this many chunks per article — a runaway body guard.
MAX_CHUNKS = 10
# Skip chunks with almost no signal.
MIN_CHUNK_CHARS = 40

_PARA_RE = re.compile(r"\n+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_units(text: str) -> list[str]:
    """Break text into paragraph units, further splitting any paragraph that is
    itself larger than one chunk into sentences."""
    units: list[str] = []
    for para in _PARA_RE.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= CHUNK_CHARS:
            units.append(para)
        else:
            units.extend(s.strip() for s in _SENT_RE.split(para) if s.strip())
    return units


def chunk_article(title: str, content: str) -> list[str]:
    """Return an ordered list of chunk texts for one article."""
    title = (title or "").strip()
    content = (content or "").strip()
    body = f"{title}\n\n{content}" if title else content
    if not body:
        return []

    units = _split_units(body)
    chunks: list[str] = []
    buf = ""
    for unit in units:
        if not buf:
            buf = unit
        elif len(buf) + 1 + len(unit) <= CHUNK_CHARS:
            buf = f"{buf} {unit}"
        else:
            chunks.append(buf)
            # Carry a short overlap tail into the next chunk for continuity.
            tail = buf[-OVERLAP_CHARS:] if OVERLAP_CHARS else ""
            buf = f"{tail} {unit}".strip() if tail else unit
        if len(chunks) >= MAX_CHUNKS:
            break

    if buf and len(chunks) < MAX_CHUNKS:
        chunks.append(buf)

    # `body` is non-empty here (we returned early above otherwise), so the
    # fallback always yields at least one chunk even if the filter drops all.
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS] or [body[:CHUNK_CHARS]]
