import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

# Track in-progress generations to avoid duplicates
_generating = {}  # item_id -> asyncio.Event


class DeepDiveConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.item_id = self.scope["url_route"]["kwargs"]["item_id"]
        await self.accept()

        # If deep dive already exists, send URL immediately
        url = await self._get_existing_url()
        if url:
            await self.send(json.dumps({"status": "ready", "url": url}))
            await self.close()
            return

        # Check if another connection is already generating this item
        if self.item_id in _generating:
            await self.send(json.dumps({"status": "generating"}))
            # Wait for the other generation to finish
            try:
                await asyncio.wait_for(_generating[self.item_id].wait(), timeout=300)
                await self.send(json.dumps({
                    "status": "ready",
                    "url": f"/deep-dive/{self.item_id}/",
                }))
            except asyncio.TimeoutError:
                await self.send(json.dumps({
                    "status": "error",
                    "message": "Generation timed out",
                }))
            await self.close()
            return

        # This connection will do the generation
        event = asyncio.Event()
        _generating[self.item_id] = event

        await self.send(json.dumps({"status": "generating"}))
        try:
            url = await self._generate()
            await self.send(json.dumps({"status": "ready", "url": url}))
        except Exception as e:
            logger.exception("Deep dive generation failed for item %s", self.item_id)
            await self.send(json.dumps({"status": "error", "message": str(e)}))
        finally:
            event.set()
            _generating.pop(self.item_id, None)

        await self.close()

    @database_sync_to_async
    def _get_existing_url(self):
        from apps.news.models import DeepDive

        dive = DeepDive.objects.filter(item_id=self.item_id).first()
        if dive:
            return f"/deep-dive/{self.item_id}/"
        return None

    @database_sync_to_async
    def _generate(self):
        from apps.news.models import DeepDive, DigestItem
        from apps.news.services.deep_dive import DeepDiveService

        # Double-check in case it was created while we waited
        if DeepDive.objects.filter(item_id=self.item_id).exists():
            return f"/deep-dive/{self.item_id}/"

        item = DigestItem.objects.select_related("section__digest").get(pk=self.item_id)
        DeepDiveService().generate(item)
        return f"/deep-dive/{self.item_id}/"
