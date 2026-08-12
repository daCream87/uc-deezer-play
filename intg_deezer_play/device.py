from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from ucapi_framework import PollingDevice

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.ma_client import MusicPlayMAClient

_LOG = logging.getLogger(__name__)


def _get(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _enum_value(value: Any, default: str = "") -> str:
    """Return enum.value when available, otherwise a plain string."""
    if value is None:
        return default
    raw = getattr(value, "value", value)
    return str(raw)


@dataclass
class MusicState:
    online: bool = False
    player_id: str = ""
    player_name: str = ""
    players: list[tuple[str, str]] = field(default_factory=list)
    state: str = "IDLE"
    volume: int = 0
    muted: bool = False
    title: str = ""
    artist: str = ""
    album: str = ""
    image_url: str = ""
    duration: int = 0
    position: int = 0
    position_updated_at: float = 0.0
    shuffle: bool = False
    repeat: str = "OFF"
    media_id: str = ""
    playlist: str = ""


class DeezerDevice(PollingDevice):
    def __init__(self, device_config: DeezerConfig, **kwargs):
        super().__init__(
            device_config,
            poll_interval=device_config.poll_interval,
            **kwargs,
        )
        self._config = device_config
        self._client = MusicPlayMAClient(
            device_config.server_url,
            device_config.access_token,
        )
        self._state = MusicState()
        self._event_refresh_task: asyncio.Task | None = None
        self._position_task: asyncio.Task | None = None

    @property
    def identifier(self):
        return self._config.identifier

    @property
    def name(self):
        return self._config.name

    @property
    def address(self):
        return self._config.server_url

    @property
    def log_id(self):
        return f"{self.name} ({self.address})"

    @property
    def state(self):
        return self._state

    @property
    def client(self):
        return self._client.client

    @property
    def server_url(self) -> str:
        return self._config.server_url.rstrip("/")

    async def establish_connection(self):
        await self._client.start(self._on_event)
        await self.poll_device()
        if not self._position_task or self._position_task.done():
            self._position_task = asyncio.create_task(
                self._position_ticker(),
                name="music-play-position-ticker",
            )
        return self._client

    async def disconnect(self):
        if self._event_refresh_task:
            self._event_refresh_task.cancel()
            self._event_refresh_task = None
        if self._position_task:
            self._position_task.cancel()
            try:
                await self._position_task
            except asyncio.CancelledError:
                pass
            self._position_task = None
        await self._client.close()
        await super().disconnect()

    def _on_event(self, _event: Any) -> None:
        # Collapse event bursts into one refresh.
        if self._event_refresh_task and not self._event_refresh_task.done():
            return
        self._event_refresh_task = asyncio.create_task(self._refresh_after_event())

    async def _refresh_after_event(self):
        await asyncio.sleep(0.15)
        try:
            await self.poll_device()
        except Exception:
            _LOG.debug("Event refresh failed", exc_info=True)

    def current_position(self) -> int:
        """Return locally extrapolated playback position without a network poll."""
        state = self._state
        position = float(state.position or 0)
        if "PLAY" in state.state.upper() and state.position_updated_at > 0:
            position += max(0.0, time.time() - state.position_updated_at)
        if state.duration > 0:
            position = min(position, float(state.duration))
        return max(0, int(position))

    async def _position_ticker(self) -> None:
        """Keep the Remote progress display live using local time only."""
        try:
            while True:
                await asyncio.sleep(1)
                if not self._state.online or "PLAY" not in self._state.state.upper():
                    continue
                # Re-anchor locally every second. No Music Assistant request is made.
                self._state.position = self.current_position()
                self._state.position_updated_at = time.time()
                self.push_update()
        except asyncio.CancelledError:
            raise

    def absolute_image_url(self, value: Any) -> str:
        """Return a Remote-3 reachable image URL without guessing MA endpoints."""
        if not value:
            return ""
        value = str(value).strip()
        if value.startswith(("http://", "https://")):
            return value
        # Player.current_media can expose MA-owned relative imageproxy URLs.
        if value.startswith("/"):
            return urljoin(self.server_url + "/", value.lstrip("/"))
        return ""

    async def poll_device(self):
        players = await self._client.players()
        pairs = [
            (
                str(_get(p, "player_id", "")),
                str(_get(p, "display_name", _get(p, "name", "Player"))),
            )
            for p in players
        ]
        pairs = [(pid, name) for pid, name in pairs if pid]
        selected = self._select_player(players)

        if not selected:
            self._state = MusicState(online=True, players=pairs)
            self.push_update()
            return

        player_id = str(_get(selected, "player_id", ""))

        queue = None
        try:
            queue = await self._client.queue(player_id)
        except Exception:
            _LOG.debug("Queue state unavailable for %s", player_id, exc_info=True)

        current = _get(queue, "current_item", None)
        media = _get(current, "media_item", current)
        player_media = _get(selected, "current_media", None)

        metadata = _get(media, "metadata", None)
        artists = _get(media, "artists", []) or []
        artist = (
            ", ".join(str(_get(a, "name", a)) for a in artists)
            if artists
            else str(
                _get(
                    player_media,
                    "artist",
                    _get(media, "artist", ""),
                )
                or ""
            )
        )

        album_obj = _get(media, "album", None)
        album = str(
            _get(
                player_media,
                "album",
                _get(album_obj, "name", _get(media, "album_name", "")),
            )
            or ""
        )

        # Most reliable artwork source is the player's PlayerMedia object.
        # MA resolves provider artwork/imageproxy URLs there.
        image_url = ""
        # Match the official Music Assistant HA integration: ask the client
        # for the canonical artwork URL for the current queue item first.
        ma_client = self._client.client
        get_image_url = getattr(ma_client, "get_media_item_image_url", None)
        if callable(get_image_url) and current is not None:
            try:
                image_url = str(get_image_url(current) or "")
            except Exception:
                _LOG.debug("Canonical MA artwork URL lookup failed", exc_info=True)

        if not image_url:
            image = (
                _get(player_media, "image_url", "")
                or _get(current, "image_url", "")
                or _get(media, "image_url", "")
                or _get(metadata, "image_url", "")
            )
            image_url = self.absolute_image_url(image)

        title = str(
            _get(
                player_media,
                "title",
                _get(media, "name", _get(current, "name", "")),
            )
            or ""
        )
        duration = int(
            _get(
                player_media,
                "duration",
                _get(current, "duration", _get(media, "duration", 0)),
            )
            or 0
        )

        queue_state = _enum_value(
            _get(
                queue,
                "state",
                _get(selected, "playback_state", _get(selected, "state", "IDLE")),
            ),
            "IDLE",
        ).upper()

        # Music Assistant provides a position *and* the timestamp at which that
        # position was measured. UC extrapolates playback from this anchor.
        # Never replace this timestamp with "now" on every poll, otherwise the
        # Remote freezes at the last sampled position.
        position = float(
            _get(
                queue,
                "elapsed_time",
                _get(selected, "elapsed_time", 0),
            )
            or 0
        )
        position_updated_at = float(
            _get(
                queue,
                "elapsed_time_last_updated",
                _get(selected, "elapsed_time_last_updated", 0),
            )
            or 0
        )

        # Sample the MA anchor to "now". The local ticker will advance it
        # continuously between MA events, so reopening the entity never jumps
        # back to an old seek/pause anchor.
        if "PLAY" in queue_state and position_updated_at > 0:
            position += max(0.0, time.time() - position_updated_at)
            if duration > 0:
                position = min(position, float(duration))
            position_updated_at = time.time()

        self._state = MusicState(
            online=True,
            player_id=player_id,
            player_name=str(
                _get(selected, "display_name", _get(selected, "name", player_id))
            ),
            players=pairs,
            state=queue_state,
            volume=int(_get(selected, "volume_level", 0) or 0),
            muted=bool(_get(selected, "volume_muted", False)),
            title=title,
            artist=artist,
            album=album,
            image_url=image_url,
            duration=duration,
            position=int(position),
            position_updated_at=position_updated_at,
            shuffle=bool(_get(queue, "shuffle_enabled", False)),
            repeat=str(_get(queue, "repeat_mode", "OFF") or "OFF")
            .upper()
            .split(".")[-1],
            media_id=str(
                _get(
                    player_media,
                    "uri",
                    _get(media, "uri", _get(current, "uri", "")),
                )
                or ""
            ),
            playlist=str(_get(queue, "display_name", "") or ""),
        )

        self._config.default_player_id = player_id
        self.push_update()

    def _select_player(self, players: list[Any]):
        if self._config.default_player_id:
            for player in players:
                if str(_get(player, "player_id", "")) == self._config.default_player_id:
                    return player

        preferred = self._config.preferred_player_name.lower().strip()
        if preferred:
            for player in players:
                name = str(
                    _get(player, "display_name", _get(player, "name", ""))
                ).lower()
                if preferred in name or (
                    "x4800" in preferred and "x4800" in name
                ):
                    return player

        for player in players:
            text = (
                f"{_get(player, 'provider', '')} "
                f"{_get(player, 'display_name', '')} "
                f"{_get(player, 'name', '')}"
            ).lower()
            if "heos" in text or "denon" in text or "x4800" in text:
                return player

        return players[0] if players else None

    async def select_player(self, value: str) -> bool:
        for pid, name in self._state.players:
            if value in (pid, name):
                self._config.default_player_id = pid
                await self.poll_device()
                return True
        return False

    async def queue_items(self, limit: int = 100, offset: int = 0) -> list[Any]:
        pid = self._state.player_id
        if not pid:
            return []
        rows = await self._client.command(
            "player_queues/items",
            queue_id=pid,
            limit=limit,
            offset=offset,
        )
        return list(rows or [])

async def send(self, command: str, **kwargs) -> bool:
    pid = self._state.player_id
    if not pid:
        return False

    try:
        ma = self._client.client
        queues = getattr(ma, "player_queues", None) if ma else None

        if command == "play_pause":
            if queues and hasattr(queues, "play_pause"):
                await queues.play_pause(pid)
            else:
                await self._client.command("player_queues/play_pause", queue_id=pid)

        elif command == "stop":
            # Stop the active Music Assistant queue, not only the physical
            # renderer. This is the canonical MA STOP operation.
            if queues and hasattr(queues, "stop"):
                await queues.stop(pid)
            else:
                await self._client.command("player_queues/stop", queue_id=pid)
            self._state.state = "IDLE"
            self._state.position = 0
            self._state.position_updated_at = time.time()
            self.push_update()

        elif command == "next":
            if queues and hasattr(queues, "next"):
                await queues.next(pid)
            else:
                await self._client.command("player_queues/next", queue_id=pid)

        elif command == "previous":
            if queues and hasattr(queues, "previous"):
                await queues.previous(pid)
            else:
                await self._client.command("player_queues/previous", queue_id=pid)

        elif command == "skip":
            seconds = int(round(float(kwargs.get("seconds", 0))))
            if not seconds:
                return True
            if queues and hasattr(queues, "skip"):
                await queues.skip(pid, seconds)
            else:
                await self._client.command(
                    "player_queues/skip",
                    queue_id=pid,
                    seconds=seconds,
                )
            self._state.position = max(
                0,
                min(
                    self._state.duration or 10**9,
                    self.current_position() + seconds,
                ),
            )
            self._state.position_updated_at = time.time()
            self.push_update()

        elif command == "seek":
            target = int(round(float(kwargs.get("position", 0))))
            if self._state.duration > 0:
                target = max(0, min(target, self._state.duration))
            else:
                target = max(0, target)
            if queues and hasattr(queues, "seek"):
                await queues.seek(pid, target)
            else:
                await self._client.command(
                    "player_queues/seek",
                    queue_id=pid,
                    position=target,
                )
            # Optimistic anchor avoids the slider snapping back while MA
            # sends the queue-time update.
            self._state.position = target
            self._state.position_updated_at = time.time()
            self.push_update()

        elif command == "volume_up":
            await self._client.command("players/cmd/volume_up", player_id=pid)

        elif command == "volume_down":
            await self._client.command("players/cmd/volume_down", player_id=pid)

        elif command == "mute_toggle":
            await self._client.command(
                "players/cmd/volume_mute",
                player_id=pid,
                muted=not self._state.muted,
            )

        elif command == "shuffle":
            enabled = bool(kwargs["enabled"])
            if queues and hasattr(queues, "shuffle"):
                await queues.shuffle(pid, enabled)
            else:
                await self._client.command(
                    "player_queues/shuffle",
                    queue_id=pid,
                    shuffle_enabled=enabled,
                )
            self._state.shuffle = enabled
            self.push_update()

        elif command == "repeat":
            mode = str(kwargs["mode"]).lower().split(".")[-1]
            await self._client.command(
                "player_queues/repeat",
                queue_id=pid,
                repeat_mode=mode,
            )

        elif command == "volume":
            await self._client.command(
                "players/cmd/volume_set",
                player_id=pid,
                volume_level=int(kwargs["volume"]),
            )

        elif command == "clear_queue":
            if queues and hasattr(queues, "clear"):
                await queues.clear(pid)
            else:
                await self._client.command("player_queues/clear", queue_id=pid)

        elif command == "play_media":
            media_id = str(kwargs["media_id"])
            option = str(kwargs.get("option", "play")).lower()
            if option not in {"play", "next", "add"}:
                option = "play"
            await self._client.command(
                "player_queues/play_media",
                queue_id=pid,
                media=media_id,
                option=option,
            )
        else:
            return False

        # Give MA a short moment to emit its authoritative queue update.
        await asyncio.sleep(0.12)
        return True
    except Exception:
        _LOG.exception("Music command failed: %s params=%s", command, kwargs)
        return False
