from urllib.parse import urlparse

from fake_useragent import UserAgent

_ua = UserAgent(platforms="desktop")


def get_domain(url: str) -> str:
    """Extract the lowercase domain from a URL."""
    return urlparse(url).netloc.lower()


def random_headers() -> dict[str, str]:
    """Return realistic random browser headers."""
    return {
        "User-Agent": _ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
