import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from readability import Document

from apps.news.models import Article

logger = logging.getLogger(__name__)

TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; Newspaper/0.1)"
MAX_WORKERS = 10


def _strip_html(text: str) -> str:
    """Remove HTML tags, decode entities, collapse whitespace."""
    import re
    from html import unescape

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse spaces within lines
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _clean_for_xml(text: str) -> str:
    """Remove NULL bytes and XML-incompatible control characters."""
    import re
    # Remove NULL bytes and control chars except \t \n \r
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _fetch_and_extract(article_id: int, url: str) -> tuple[int, str, str | None]:
    """Download page and extract main content. Runs in a thread.

    Returns (article_id, clean_text, error_or_none).
    """
    try:
        resp = requests.get(
            url, timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()

        html = _clean_for_xml(resp.text)
        doc = Document(html)
        html_content = doc.summary()
        clean_text = _strip_html(html_content)

        if len(clean_text) < 50:
            return article_id, "", f"Content too short ({len(clean_text)} chars)"

        return article_id, clean_text, None
    except Exception as e:
        return article_id, "", str(e)


class ContentExtractor:
    """Extract full article text from URLs using readability."""

    def __init__(self, workers: int = MAX_WORKERS, stdout=None):
        self.workers = workers
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def extract_new(self) -> tuple[int, int, list[str]]:
        """Extract content for articles not yet fetched.

        Returns (total, extracted, errors).
        """
        articles = list(
            Article.objects.filter(content_fetched=False)
            .exclude(url="")
            .values_list("id", "url")
        )

        if not articles:
            self._write("No articles to extract.\n")
            return 0, 0, []

        self._write(f"Extracting content for {len(articles)} articles...\n")

        extracted = 0
        errors = []

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_fetch_and_extract, aid, url): aid
                for aid, url in articles
            }

            done_count = 0
            for future in as_completed(futures):
                article_id, clean_text, error = future.result()
                done_count += 1

                if error:
                    errors.append(error)
                    # Mark as fetched even on failure — don't retry
                    Article.objects.filter(id=article_id).update(
                        content_fetched=True
                    )
                else:
                    Article.objects.filter(id=article_id).update(
                        content=clean_text,
                        content_fetched=True,
                    )
                    extracted += 1

                if done_count % 100 == 0:
                    self._write(
                        f"  {done_count}/{len(articles)} processed "
                        f"({extracted} ok, {len(errors)} failed)\n"
                    )

        self._write(
            f"Done: {extracted}/{len(articles)} extracted "
            f"({len(errors)} failed)\n"
        )
        return len(articles), extracted, errors
