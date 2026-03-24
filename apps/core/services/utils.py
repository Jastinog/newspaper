def deduplicate_queries(queries: list[str], limit: int) -> list[str]:
    """Deduplicate queries case-insensitively, preserving order, up to limit."""
    seen = set()
    unique = []
    for q in queries:
        key = q.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:limit]
