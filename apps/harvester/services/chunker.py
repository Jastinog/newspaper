"""Recursive text chunker for embedding.

Splits text using a hierarchy of separators (paragraphs -> lines -> sentences -> words),
targeting ~512 tokens (~2000 chars) per chunk with 10% overlap.
"""

TARGET_CHARS = 2000
MAX_CHARS = 2500
MIN_CHARS = 200
OVERLAP_CHARS = 200

# Separators in priority order: paragraphs, lines, sentences, words
SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]


def strip_html(text: str) -> str:
    """Remove HTML tags from text, handling quoted attributes correctly."""
    result = []
    in_tag = False
    in_quote = None

    for ch in text:
        if in_tag:
            if in_quote is not None:
                if ch == in_quote:
                    in_quote = None
            else:
                if ch in ('"', "'"):
                    in_quote = ch
                elif ch == ">":
                    in_tag = False
                    in_quote = None
        elif ch == "<":
            in_tag = True
        else:
            result.append(ch)

    return "".join(result)


def _recursive_split(text: str, separators: list[str]) -> list[str]:
    """Split text recursively using separator hierarchy.

    Tries the first separator. Pieces that fit within TARGET_CHARS are kept.
    Pieces that are too large are split recursively with the next separator.
    """
    if len(text) <= TARGET_CHARS:
        return [text]

    if not separators:
        # Last resort: hard split at word boundary
        return _hard_split(text, TARGET_CHARS)

    sep = separators[0]
    rest = separators[1:]

    parts = text.split(sep)

    # If this separator didn't split anything, try next
    if len(parts) == 1:
        return _recursive_split(text, rest)

    # Re-attach separator to each piece (except last) for natural reading
    # For sentence-ending separators (". ", "! ", "? "), append to the piece
    # For structural separators (\n\n, \n), don't append
    is_sentence_sep = sep in (". ", "! ", "? ", "; ", ", ")

    pieces = []
    for i, part in enumerate(parts):
        if is_sentence_sep and i < len(parts) - 1:
            pieces.append(part + sep.rstrip())
        else:
            pieces.append(part)

    # Merge small consecutive pieces into chunks of ~TARGET_CHARS
    chunks = []
    current = ""

    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue

        # If a single piece is too large, recurse with finer separator
        if len(piece) > TARGET_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_recursive_split(piece, rest))
            continue

        joiner = sep if not is_sentence_sep else " "
        if not current:
            current = piece
        elif len(current) + len(joiner) + len(piece) <= TARGET_CHARS:
            current += joiner + piece
        else:
            chunks.append(current)
            current = piece

    if current:
        chunks.append(current)

    return chunks


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Split text into pieces of max_chars, breaking at word boundaries."""
    pieces = []
    while len(text) > max_chars:
        split_at = text.rfind(" ", 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        pieces.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        pieces.append(text)
    return pieces


def _merge_small(chunks: list[str]) -> list[str]:
    """Merge chunks smaller than MIN_CHARS with neighbors."""
    if len(chunks) <= 1:
        return chunks

    merged = [chunks[0]]
    for chunk in chunks[1:]:
        if len(merged[-1]) < MIN_CHARS:
            merged[-1] += "\n" + chunk
        elif len(chunk) < MIN_CHARS:
            merged[-1] += "\n" + chunk
        else:
            merged.append(chunk)

    return merged


def _add_overlap(chunks: list[str]) -> list[str]:
    """Add overlap from the end of previous chunk to start of next."""
    if len(chunks) <= 1 or OVERLAP_CHARS <= 0:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        curr = chunks[i]

        # Take last ~OVERLAP_CHARS from previous chunk, at word boundary
        if len(prev) <= OVERLAP_CHARS:
            overlap = prev
        else:
            cut = prev[-(OVERLAP_CHARS):]
            word_start = cut.find(" ")
            if word_start != -1:
                overlap = cut[word_start + 1:]
            else:
                overlap = cut

        result.append(f"...{overlap}\n\n{curr}")

    return result


def _enforce_hard_max(chunks: list[str]) -> list[str]:
    """Safety net: hard-split any chunk still exceeding MAX_CHARS."""
    final = []
    for chunk in chunks:
        if len(chunk) > MAX_CHARS:
            final.extend(_hard_split(chunk, TARGET_CHARS))
        else:
            final.append(chunk)
    return final


def chunk_text(title: str, content: str) -> list[str]:
    """Split article into chunks for embedding.

    Uses recursive splitting (paragraphs -> lines -> sentences -> words),
    targeting ~2000 chars per chunk with ~200 char overlap.
    Title is prepended to the first chunk only.
    Content is expected to be clean text (no HTML).
    """
    if not content.strip():
        return [title] if title else []

    full_text = f"{title}\n\n{content}" if title else content

    # Step 1: Recursive split by separator hierarchy
    chunks = _recursive_split(full_text, SEPARATORS)

    # Step 2: Merge undersized chunks
    chunks = _merge_small(chunks)

    # Step 3: Add overlap between chunks
    chunks = _add_overlap(chunks)

    # Step 4: Safety — enforce hard max
    chunks = _enforce_hard_max(chunks)

    # Filter empty
    chunks = [c.strip() for c in chunks if c.strip()]

    return chunks if chunks else [full_text[:MAX_CHARS]]
