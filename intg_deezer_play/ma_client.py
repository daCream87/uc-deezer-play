from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from music_assistant_client import MusicAssistantClient

_LOG = logging.getLogger(__name__)


class DeezerMAClient:
    """Small resilient wrapper around the official Music Assistant Python client."""

    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.client: MusicAssistantClient | None = None
        self._listen_task: asyncio.Task | None = None
        self._event_callback: Callable[[Any], None] | None = None

    async def start(self, event_callback: Callable[[Any], None] | None = None) -> None:
        await self.close()
        self._event_callback = event_callback
        client = MusicAssistantClient(self.server_url, None, token=self.token or None)
        await client.__aenter__()
        self.client = client
        if event_callback:
            client.subscribe(event_callback)
        self._listen_task = asyncio.create_task(client.start_listening(), name="deezer-ma-listener")
        # Give authentication/initial-state exchange a short head start.
        await asyncio.sleep(0.25)

    async def close(self) -> None:
        task = self._listen_task
        self._listen_task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                _LOG.debug("Music Assistant listener stopped with error", exc_info=True)
        client = self.client
        self.client = None
        if client:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                _LOG.debug("Music Assistant client close failed", exc_info=True)

    async def command(self, command: str, **kwargs):
        if not self.client:
            raise ConnectionError("Music Assistant is not connected")
        return await self.client.send_command(command, **kwargs)

    async def players(self) -> list[Any]:
        result = await self.command("players/all")
        return list(result or [])

    async def queue(self, player_id: str) -> Any:
        return await self.command("player_queues/get", queue_id=player_id)
