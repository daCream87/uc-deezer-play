from __future__ import annotations

import asyncio
import inspect
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable

from music_assistant_client import MusicAssistantClient

_LOG = logging.getLogger(__name__)


class MusicPlayMAClient:
    """Resilient wrapper around the official Music Assistant Python client."""

    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.client: MusicAssistantClient | None = None
        self._listen_task: asyncio.Task | None = None
        self._unsubscribe = None

    async def start(self, event_callback: Callable[[Any], None] | None = None) -> None:
        await self.close()

        try:
            client_version = version("music-assistant-client")
        except PackageNotFoundError:
            client_version = "unknown"
        _LOG.info("Using music-assistant-client %s", client_version)

        # Keep constructor arguments compatible with released 1.x clients.
        # Some releases do not yet support the optional `locale` parameter.
        client = MusicAssistantClient(
            self.server_url,
            None,
            token=self.token or None,
        )
        self.client = client

        if event_callback:
            self._unsubscribe = client.subscribe(event_callback)

        start_params = inspect.signature(client.start_listening).parameters
        ready = asyncio.Event()

        if "init_ready" in start_params:
            task = asyncio.create_task(
                client.start_listening(init_ready=ready),
                name="music-play-ma-listener",
            )
        else:
            task = asyncio.create_task(
                client.start_listening(),
                name="music-play-ma-listener",
            )

        self._listen_task = task

        # Newer clients provide init_ready. On older clients wait until the
        # connection is authenticated and the initial player cache is populated.
        if "init_ready" in start_params:
            try:
                await asyncio.wait_for(ready.wait(), timeout=20)
            except asyncio.TimeoutError as err:
                if task.done():
                    exc = task.exception()
                    await self.close()
                    if exc:
                        raise ConnectionError(
                            f"Music Assistant connection failed: {type(exc).__name__}: {exc}"
                        ) from exc
                await self.close()
                raise TimeoutError(
                    f"Music Assistant at {self.server_url} did not become ready within 20 seconds"
                ) from err
        else:
            for _ in range(80):
                if task.done():
                    exc = task.exception()
                    await self.close()
                    if exc:
                        raise ConnectionError(
                            f"Music Assistant connection failed: {type(exc).__name__}: {exc}"
                        ) from exc
                    raise ConnectionError("Music Assistant connection closed during startup")
                if getattr(client, "server_info", None) is not None:
                    # Give older clients a short moment to fetch their initial caches.
                    await asyncio.sleep(0.5)
                    break
                await asyncio.sleep(0.25)
            else:
                await self.close()
                raise TimeoutError(
                    f"Music Assistant at {self.server_url} did not connect within 20 seconds"
                )

        _LOG.info(
            "Connected to Music Assistant at %s (players=%d)",
            self.server_url,
            len(getattr(client.players, "players", []) or []),
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
        cached = list(getattr(self.client.players, "players", []) or [])
        if cached:
            return cached

        # Compatibility fallback for older client versions.
        rows = await self.client.send_command("players/all")
        return list(rows or [])

    async def queue(self, player_id: str) -> Any:
        if not self.client:
            raise ConnectionError("Music Assistant is not connected")

        queues = self.client.player_queues
        get_fn = getattr(queues, "get", None)
        if callable(get_fn):
            queue = get_fn(player_id)
            if queue is not None:
                return queue

        get_active = getattr(queues, "get_active_queue", None)
        if callable(get_active):
            queue = await get_active(player_id)
            if queue is not None:
                return queue

        return await self.command("player_queues/get", queue_id=player_id)
