from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from music_assistant_client import MusicAssistantClient

_LOG = logging.getLogger(__name__)


class DeezerMAClient:
    """Resilient wrapper around the official Music Assistant Python client."""

    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.client: MusicAssistantClient | None = None
        self._listen_task: asyncio.Task | None = None
        self._unsubscribe = None

    async def start(self, event_callback: Callable[[Any], None] | None = None) -> None:
        await self.close()

        client = MusicAssistantClient(
            self.server_url,
            None,
            token=self.token or None,
            locale="de_DE",
        )
        self.client = client

        if event_callback:
            self._unsubscribe = client.subscribe(event_callback)

        # start_listening() performs connect + authentication and then fetches
        # providers, queues and players. Do not poll the server before this
        # initial state is ready.
        ready = asyncio.Event()
        task = asyncio.create_task(
            client.start_listening(init_ready=ready),
            name="deezer-ma-listener",
        )
        self._listen_task = task

        ready_wait = asyncio.create_task(ready.wait())
        done, pending = await asyncio.wait(
            {task, ready_wait},
            timeout=20,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for pending_task in pending:
            if pending_task is ready_wait:
                pending_task.cancel()

        if ready.is_set():
            _LOG.info(
                "Connected to Music Assistant at %s (players=%d)",
                self.server_url,
                len(client.players.players),
            )
            return

        # Listener exited before initial state was ready, or timed out.
        if task.done():
            exc = task.exception()
            await self.close()
            if exc:
                raise ConnectionError(
                    f"Music Assistant connection failed: {type(exc).__name__}: {exc}"
                ) from exc
            raise ConnectionError("Music Assistant connection closed during startup")

        await self.close()
        raise TimeoutError(
            f"Music Assistant at {self.server_url} did not become ready within 20 seconds"
        )

    async def close(self) -> None:
        if self._unsubscribe:
            try:
                self._unsubscribe()
            except Exception:
                _LOG.debug("Could not remove Music Assistant event subscription", exc_info=True)
            self._unsubscribe = None

        client = self.client
        self.client = None

        task = self._listen_task
        self._listen_task = None

        if client:
            try:
                await client.disconnect()
            except Exception:
                _LOG.debug("Music Assistant disconnect failed", exc_info=True)

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                _LOG.debug("Music Assistant listener stopped with error", exc_info=True)

    async def command(self, command: str, **kwargs):
        if not self.client:
            raise ConnectionError("Music Assistant is not connected")
        return await self.client.send_command(command, **kwargs)

    async def players(self) -> list[Any]:
        if not self.client:
            raise ConnectionError("Music Assistant is not connected")
        # Use the official client's initialized player cache.
        return list(self.client.players.players)

    async def queue(self, player_id: str) -> Any:
        if not self.client:
            raise ConnectionError("Music Assistant is not connected")
        queue = self.client.player_queues.get(player_id)
        if queue is not None:
            return queue
        return await self.command("player_queues/get", queue_id=player_id)
