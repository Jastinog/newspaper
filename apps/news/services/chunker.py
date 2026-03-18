MAX_CHUNK_CHARS = 1000
MIN_CHUNK_CHARS = 100


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


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving punctuation.

    Splits on [.!?] followed by space/newline.
    """
    sentences = []
    current = []
    chars = list(text)

    for i, ch in enumerate(chars):
        current.append(ch)

        if ch in (".", "!", "?"):
            next_ch = chars[i + 1] if i + 1 < len(chars) else None
            if next_ch in (" ", "\n"):
                trimmed = "".join(current).strip()
                if trimmed:
                    sentences.append(trimmed)
                current = []

    trimmed = "".join(current).strip()
    if trimmed:
        sentences.append(trimmed)

    return sentences


def chunk_text(title: str, content: str) -> list[str]:
    """Split article into chunks by sentences with ~1000 char limit.

    Content is expected to be clean text (no HTML).
    """
    full_text = f"{title}\n\n{content}"

    sentences = _split_into_sentences(full_text)

    if not sentences:
        return [full_text]

    chunks: list[str] = []
    current_chunk = ""

    for sentence in sentences:
        if current_chunk and len(current_chunk) + 1 + len(sentence) > MAX_CHUNK_CHARS:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence

    if current_chunk:
        if len(current_chunk) < MIN_CHUNK_CHARS:
            if chunks:
                chunks[-1] += " " + current_chunk
            else:
                chunks.append(current_chunk)
        else:
            chunks.append(current_chunk)

    if not chunks:
        chunks.append(full_text)

    return chunks
