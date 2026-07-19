"""Guards for the on-demand article summary feature (a paid OpenAI call).

Kept dependency-free (only Django) so templates and the WebSocket consumer can
import it cheaply, without pulling in the OpenAI client. Three checks combine to
keep generation human-and-browser-only:

  * `origin_ok`        — the WS Origin header must be one of our own hosts;
  * `summary_token_*`  — a short-lived signed token embedded in the article card,
                         proving the page was actually rendered by us for this
                         exact article (a blind script has no valid token);
  * `trusted_peer`     — the real client IP for rate limiting, read as the last
                         X-Forwarded-For hop (the one our nginx appends, which a
                         client cannot spoof), not REMOTE_ADDR (always the proxy).

The spend cap itself lives in `summarize.summary_rate_ok`.
"""
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing

_TOKEN_SALT = "article-summary-token"
# A rendered article page stays good for a browsing session, then must be reloaded.
_TOKEN_MAX_AGE = 60 * 60 * 6  # 6 hours


def make_summary_token(article_id) -> str:
    """Signed, time-stamped token binding a summary request to one article."""
    return signing.dumps({"a": int(article_id)}, salt=_TOKEN_SALT)


def summary_token_ok(token, article_id) -> bool:
    """True iff `token` is our signature, unexpired, and issued for `article_id`."""
    if not token:
        return False
    try:
        data = signing.loads(token, salt=_TOKEN_SALT, max_age=_TOKEN_MAX_AGE)
    except signing.BadSignature:  # covers SignatureExpired
        return False
    try:
        return int(data.get("a")) == int(article_id)
    except (TypeError, ValueError):
        return False


def origin_ok(origin) -> bool:
    """True iff the browser Origin host is one of our ALLOWED_HOSTS."""
    if not origin:
        return False
    host = (urlsplit(origin).hostname or "").lower()
    allowed = settings.ALLOWED_HOSTS
    if "*" in allowed:
        return True
    return host in {h.lower() for h in allowed}


def trusted_peer(xff, remote_addr) -> str:
    """The real client IP behind our single nginx.

    nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, appending the true
    TCP peer as the LAST entry; anything a client prepends stays to its left. So
    the last hop is the one identifier a caller cannot forge. Falls back to
    REMOTE_ADDR only when no forwarding header is present (direct/local access).
    """
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return remote_addr or "unknown"
