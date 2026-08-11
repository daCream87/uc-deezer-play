from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from ucapi_framework import PollingDevice

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.ma_client import DeezerMAClient

_LOG = logging.getLogger(__name__)


def _get(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


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
    shuffle: bool = False
    repeat: str = "OFF"
    media_id: str = ""
    playlist: str = ""


class DeezerDevice(PollingDevice):
    def __init__(self, device_config: DeezerConfig, **kwargs):
        super().__init__(device_config, poll_interval=device_config.poll_interval, **kwargs)
        self._config = device_config
        self._client = DeezerMAClient(device_config.server_url, device_config.access_token)
        self._state = MusicState()
        self._event_refresh_task: asyncio.Task | None = None

    @property
    def identifier(self): return self._config.identifier
    @property
    def name(self): return self._config.name
    @property
    def address(self): return self._config.server_url

    @property
    def log_id(self):
        # Required by ucapi_framework BaseDevice/PollingDevice.
        # Keep the same proven pattern used by the working Titan integration.
        return f"{self.name} ({self.address})"

    @property
    def state(self): return self._state
    @property
    def client(self): return self._client.client

    async def establish_connection(self):
        await self._client.start(self._on_event)
        await self.poll_device()
        return self._client

    async def disconnect(self):
        if self._event_refresh_task:
            self._event_refresh_task.cancel()
            self._event_refresh_task = None
        await self._client.close()
        await super().disconnect()

    def _on_event(self, _event: Any) -> None:
        # Collapse event bursts to one refresh and keep the UC status event-driven.
        if self._event_refresh_task and not self._event_refresh_task.done():
            return
        self._event_refresh_task = asyncio.create_task(self._refresh_after_event())

    async def _refresh_after_event(self):
        await asyncio.sleep(0.15)
        try:
            await self.poll_device()
        except Exception:
            _LOG.debug("Event refresh failed", exc_info=True)

    async def poll_device(self):
        players = await self._client.players()
        pairs = [(str(_get(p, "player_id", "")), str(_get(p, "display_name", _get(p, "name", "Player")))) for p in players]
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
        metadata = _get(media, "metadata", None)
        artists = _get(media, "artists", []) or []
        artist = ", ".join(str(_get(a, "name", a)) for a in artists) if artists else str(_get(media, "artist", ""))
        album_obj = _get(media, "album", None)
        album = str(_get(album_obj, "name", _get(media, "album_name", "")) or "")
        image = _get(metadata, "image_url", "") or _get(media, "image_url", "") or _get(current, "image_url", "")

        queue_state = str(_get(queue, "state", _get(selected, "state", "IDLE"))).upper()
        self._state = MusicState(
            online=True,
            player_id=player_id,
            player_name=str(_get(selected, "display_name", _get(selected, "name", player_id))),
            players=pairs,
            state=queue_state,
            volume=int(_get(selected, "volume_level", 0) or 0),
            muted=bool(_get(selected, "volume_muted", False)),
            title=str(_get(media, "name", _get(current, "name", "")) or ""),
            artist=artist,
            album=album,
            image_url=str(image or ""),
            duration=int(_get(queue, "current_item", None) and (_get(current, "duration", 0) or _get(media, "duration", 0) or 0) or 0),
            position=int(float(_get(queue, "elapsed_time", 0) or 0)),
            shuffle=bool(_get(queue, "shuffle_enabled", False)),
            repeat=str(_get(queue, "repeat_mode", "OFF") or "OFF").upper().split(".")[-1],
            media_id=str(_get(media, "uri", _get(current, "uri", "")) or ""),
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
                name = str(_get(player, "display_name", _get(player, "name", ""))).lower()
                if preferred in name or ("x4800" in preferred and "x4800" in name):
                    return player
        # Prefer HEOS/Denon when possible, otherwise first available player.
        for player in players:
            text = f"{_get(player, 'provider', '')} {_get(player, 'display_name', '')} {_get(player, 'name', '')}".lower()
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

    async def send(self, command: str, **kwargs) -> bool:
        pid = self._state.player_id
        if not pid:
            return False
        try:
            if command == "play_pause": await self._client.command("player_queues/play_pause", queue_id=pid)
            elif command == "stop": await self._client.command("players/cmd/stop", player_id=pid)
            elif command == "next": await self._client.command("players/cmd/next", player_id=pid)
            elif command == "previous": await self._client.command("players/cmd/previous", player_id=pid)
            elif command == "volume_up": await self._client.command("players/cmd/volume_up", player_id=pid)
            elif command == "volume_down": await self._client.command("players/cmd/volume_down", player_id=pid)
            elif command == "mute_toggle": await self._client.command("players/cmd/volume_mute", player_id=pid, muted=not self._state.muted)
            elif command == "shuffle": await self._client.command("player_queues/shuffle", queue_id=pid, shuffle_enabled=bool(kwargs["enabled"]))
            elif command == "repeat": await self._client.command("player_queues/repeat", queue_id=pid, repeat_mode=str(kwargs["mode"]).lower())
            elif command == "seek": await self._client.command("player_queues/seek", queue_id=pid, position=float(kwargs["position"]))
            elif command == "volume": await self._client.command("players/cmd/volume_set", player_id=pid, volume_level=int(kwargs["volume"]))
            elif command == "play_media":
                if not self.client: return False
                await self.client.player_queues.play_media(queue_id=pid, media=kwargs["media_id"])
            else: return False
            await asyncio.sleep(0.08)
            return True
        except Exception:
            _LOG.exception("Music command failed: %s", command)
            return False
