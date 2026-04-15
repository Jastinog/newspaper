import functools

import tiktoken


@functools.lru_cache(maxsize=1)
def _get_encoder():
    return tiktoken.encoding_for_model("gpt-4o")


def count_tokens(text: str) -> int:
    """Count tokens in text using the standard encoding."""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def trim_to_tokens(text: str, max_tokens: int) -> str:
    """Trim text to fit within max_tokens, breaking at paragraph or sentence boundaries."""
    if not text:
        return ""
    enc = _get_encoder()
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text

    truncated = enc.decode(tokens[:max_tokens])

    # Prefer paragraph boundary
    last_para = truncated.rfind('\n\n')
    if last_para > len(truncated) * 0.5:
        return truncated[:last_para].rstrip()

    # Try sentence boundary
    for sep in ('. ', '! ', '? ', '.\n', '!\n', '?\n'):
        pos = truncated.rfind(sep)
        if pos > len(truncated) * 0.5:
            return truncated[:pos + 1]

    return truncated
