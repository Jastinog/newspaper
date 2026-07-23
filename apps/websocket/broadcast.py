"""Server-side WebSocket broadcasts to homepage clients.

Single source of truth for the channel-layer group name and event type, shared
by the producer (harvester pipeline) and the consumer (SiteConsumer). A no-op
when no channel layer is configured (e.g. in tests).
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

HOME_GROUP = "home"
HOME_ARTICLE_EVENT = "home.article"


def broadcast_home_article(section_slug: str, article_id: int) -> None:
    """Push a 'new article in section' event to subscribed homepage clients.

    Called from the harvester's worker thread, so the async group_send is wrapped
    in a sync shim."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            HOME_GROUP,
            {"type": HOME_ARTICLE_EVENT, "section_slug": section_slug, "article_id": article_id},
        )
    except Exception:
        logger.exception("Failed to broadcast new article %s", article_id)
