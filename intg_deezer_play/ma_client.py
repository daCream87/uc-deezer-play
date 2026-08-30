from __future__ import annotations

import asyncio
import inspect
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable

from music_assistant_client import MusicAssistantClient, login_with_token

_LOG = logging.getLogger(__name__)



async def create_long_lived_token(
    server_url: str,
    username: str,
    password: str,
    token_name: str = "Music Play Remote 3",
) -> str:
    """Authenticate once and return a long-lived Music Assistant token."""
    _user, token = await login_with_token(
        server_url.rstrip("/"),
        username,
        password,
        token_name=token_name,
    )
    return str(token)


class MusicPlayMAClient:
    """Resilient wrapper around the official Music Assistant Python client."""

    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.client: MusicAssistantClient | None = None
        self._listen_task: asyncio.Task | None = None
        self._unsubscribe = None

    @property
    def is_connected(self) -> bool:
        client = self.client
        if client is None:
            return False
        connected = getattr(client, "connected", None)
        if isinstance(connected, bool):
            return connected
        return bool(
            getattr(client, "server_info", None)
            and self._listen_task
            and not self._listen_task.done()
        )

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
        """Return the actual active Music Assistant queue for a player.

        Newer Music Assistant versions expose get_active_queue(player_id)
        explicitly. Prefer it before falling back to the historical assumption
        that queue_id == player_id. This also handles grouped players correctly.
        """
        if not self.client:
            raise ConnectionError("Music Assistant is not connected")

        queues = self.client.player_queues

        get_active = getattr(queues, "get_active_queue", None)
        if callable(get_active):
            queue = await get_active(player_id)
            if queue is not None:
                return queue

        # Current Player models expose active_source. If it points to a cached
        # Music Assistant queue, resolve that queue before trying player_id.
        players = getattr(self.client, "players", None)
        player_get = getattr(players, "get", None)
        queue_get = getattr(queues, "get", None)
        if callable(player_get) and callable(queue_get):
            player = player_get(player_id)
            active_source = getattr(player, "active_source", None) if player else None
            if active_source:
                queue = queue_get(str(active_source))
                if queue is not None:
                    return queue

        if callable(queue_get):
            queue = queue_get(player_id)
            if queue is not None:
                return queue

        # Compatibility fallback for older servers/clients.
        return await self.command("player_queues/get", queue_id=player_id)
