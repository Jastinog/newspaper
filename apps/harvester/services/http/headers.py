from fake_useragent import UserAgent


class BrowserHeaders:
    """Realistic random browser request headers."""

    _ua = UserAgent(platforms="desktop")

    @classmethod
    def random(cls) -> dict[str, str]:
        """Return a fresh set of realistic browser headers with a random UA."""
        return {
            "User-Agent": cls._ua.random,
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
