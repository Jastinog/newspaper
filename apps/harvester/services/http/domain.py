from urllib.parse import urlparse


class Domain:
    """Domain extraction from URLs."""

    @staticmethod
    def of(url: str) -> str:
        """Return the lowercase domain (netloc) of a URL."""
        return urlparse(url).netloc.lower()
