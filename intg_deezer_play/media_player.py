from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ucapi import StatusCodes
from ucapi.api_definitions import Pagination
from ucapi.media_player import (
    Attributes, BrowseMediaItem, BrowseOptions, BrowseResults, Commands, DeviceClasses,
    Features, MediaClass, MediaContentType, MediaPlayer, RepeatMode, SearchOptions,
    SearchResults, States,
)
from ucapi_framework import MediaPlayerEntity

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.device import DeezerDevice

_LOG = logging.getLogger(__name__)


class DeezerMediaPlayer(MediaPlayerEntity):
    def __init__(self, device_config: DeezerConfig, device: DeezerDevice):
        self._device = device
        super().__init__(
            f"media_player.{device_config.identifier}",
            device_config.name,
            features=[
                Features.PLAY_PAUSE, Features.STOP, Features.PREVIOUS, Features.NEXT,
                Features.VOLUME, Features.VOLUME_UP_DOWN, Features.MUTE_TOGGLE,
                Features.SHUFFLE, Features.REPEAT, Features.SEEK,
                Features.MEDIA_DURATION, Features.MEDIA_POSITION, Features.MEDIA_TITLE,
                Features.MEDIA_ARTIST, Features.MEDIA_ALBUM, Features.MEDIA_IMAGE_URL,
                Features.SELECT_SOURCE, Features.PLAY_MEDIA, Features.BROWSE_MEDIA,
                Features.SEARCH_MEDIA,
            ],
            attributes={Attributes.STATE: States.UNKNOWN},
            device_class=DeviceClasses.RECEIVER,
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        s = self._device.state
        if not s.online:
            self.update({Attributes.STATE: States.UNAVAILABLE})
            return
        raw = s.state
        state = States.PLAYING if "PLAY" in raw else States.PAUSED if "PAUSE" in raw else States.ON
        attrs = {
            Attributes.STATE: state,
            Attributes.VOLUME: s.volume,
            Attributes.MUTED: s.muted,
            Attributes.MEDIA_TITLE: s.title,
            Attributes.MEDIA_ARTIST: s.artist,
            Attributes.MEDIA_ALBUM: s.album,
            Attributes.MEDIA_DURATION: s.duration,
            Attributes.MEDIA_POSITION: s.position,
            Attributes.MEDIA_POSITION_UPDATED_AT: datetime.now(timezone.utc).isoformat(),
            Attributes.MEDIA_IMAGE_URL: s.image_url,
            Attributes.MEDIA_ID: s.media_id,
            Attributes.MEDIA_PLAYLIST: s.playlist,
            Attributes.SHUFFLE: s.shuffle,
            Attributes.REPEAT: s.repeat if s.repeat in ("OFF", "ALL", "ONE") else "OFF",
            Attributes.SOURCE: s.player_name,
            Attributes.SOURCE_LIST: [name for _, name in s.players],
        }
        self.update(attrs)

    async def _handle_command(self, entity: MediaPlayer, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        p = params or {}
        try:
            if cmd_id == Commands.PLAY_PAUSE: ok = await self._device.send("play_pause")
            elif cmd_id == Commands.STOP: ok = await self._device.send("stop")
            elif cmd_id == Commands.NEXT: ok = await self._device.send("next")
            elif cmd_id == Commands.PREVIOUS: ok = await self._device.send("previous")
            elif cmd_id == Commands.VOLUME_UP: ok = await self._device.send("volume_up")
            elif cmd_id == Commands.VOLUME_DOWN: ok = await self._device.send("volume_down")
            elif cmd_id == Commands.MUTE_TOGGLE: ok = await self._device.send("mute_toggle")
            elif cmd_id == Commands.VOLUME: ok = await self._device.send("volume", volume=p.get("volume", 0))
            elif cmd_id == Commands.SEEK: ok = await self._device.send("seek", position=p.get("media_position", p.get("position", 0)))
            elif cmd_id == Commands.SHUFFLE: ok = await self._device.send("shuffle", enabled=p.get("shuffle", False))
            elif cmd_id == Commands.REPEAT: ok = await self._device.send("repeat", mode=p.get("repeat", RepeatMode.OFF))
            elif cmd_id == Commands.SELECT_SOURCE: ok = await self._device.select_player(str(p.get("source", "")))
            elif cmd_id == Commands.PLAY_MEDIA: ok = await self._device.send("play_media", media_id=str(p.get("media_id", "")))
            else: return StatusCodes.NOT_IMPLEMENTED
            return StatusCodes.OK if ok else StatusCodes.BAD_REQUEST
        except Exception:
            _LOG.exception("UC media command failed: %s", cmd_id)
            return StatusCodes.SERVER_ERROR

    async def browse(self, options: BrowseOptions) -> BrowseResults | StatusCodes:
        client = self._device.client
        if not client:
            return StatusCodes.SERVICE_UNAVAILABLE
        try:
            media_id = options.media_id or "root"
            if media_id == "root":
                items = [
                    BrowseMediaItem(media_id="library://playlists", title="Playlists", media_class=MediaClass.DIRECTORY, can_browse=True, thumbnail="icon://uc:playlist"),
                    BrowseMediaItem(media_id="library://tracks", title="Favoriten / Titel", media_class=MediaClass.DIRECTORY, can_browse=True, thumbnail="icon://uc:favorite"),
                    BrowseMediaItem(media_id="library://albums", title="Alben", media_class=MediaClass.DIRECTORY, can_browse=True, thumbnail="icon://uc:album"),
                    BrowseMediaItem(media_id="library://artists", title="Künstler", media_class=MediaClass.DIRECTORY, can_browse=True, thumbnail="icon://uc:artist"),
                ]
                root = BrowseMediaItem(media_id="root", title="Deezer", media_class=MediaClass.MUSIC, can_browse=True, can_search=True, items=items)
                return BrowseResults(media=root, pagination=Pagination(page=1, limit=len(items), count=len(items)))

            if media_id.startswith("library://"):
                kind = media_id.split("//", 1)[1]
                method = {
                    "playlists": client.music.get_library_playlists,
                    "tracks": client.music.get_library_tracks,
                    "albums": client.music.get_library_albums,
                    "artists": client.music.get_library_artists,
                }.get(kind)
                if not method: return StatusCodes.NOT_FOUND
                rows = await method(limit=100, offset=0)
                items = [self._item(x, kind) for x in rows]
                root = BrowseMediaItem(media_id=media_id, title=kind.title(), media_class=MediaClass.DIRECTORY, can_browse=True, items=items)
                return BrowseResults(media=root, pagination=Pagination(page=1, limit=len(items), count=len(items)))

            # Delegate deeper hierarchy to Music Assistant's provider-aware browser.
            result = await client.music.browse(path=media_id)
            rows = getattr(result, "items", result if isinstance(result, list) else []) or []
            items = [self._item(x, "browse") for x in rows]
            root = BrowseMediaItem(media_id=media_id, title=getattr(result, "name", "Deezer"), media_class=MediaClass.DIRECTORY, can_browse=True, items=items)
            return BrowseResults(media=root, pagination=Pagination(page=1, limit=len(items), count=len(items)))
        except Exception:
            _LOG.exception("Browse failed: %s", options)
            return StatusCodes.SERVER_ERROR

    async def search(self, options: SearchOptions) -> SearchResults | StatusCodes:
        client = self._device.client
        if not client:
            return StatusCodes.SERVICE_UNAVAILABLE
        try:
            result = await client.music.search(search_query=options.query, limit=50)
            rows = []
            for attr in ("tracks", "playlists", "albums", "artists"):
                rows.extend(getattr(result, attr, []) or [])
            items = [self._item(x, "search") for x in rows]
            return SearchResults(media=items, pagination=Pagination(page=1, limit=len(items), count=len(items)))
        except Exception:
            _LOG.exception("Search failed: %s", options.query)
            return StatusCodes.SERVER_ERROR

    @staticmethod
    def _item(obj: Any, kind: str) -> BrowseMediaItem:
        def g(name, default=None):
            if isinstance(obj, dict): return obj.get(name, default)
            return getattr(obj, name, default)
        uri = str(g("uri", g("item_id", "")))
        name = str(g("name", "Unbenannt"))
        media_type = str(g("media_type", kind)).lower().split(".")[-1]
        can_browse = media_type in ("playlist", "album", "artist")
        can_play = media_type in ("track", "playlist", "album")
        metadata = g("metadata")
        image = getattr(metadata, "image_url", None) if metadata else None
        artists = g("artists", []) or []
        artist = ", ".join(str(getattr(a, "name", a)) for a in artists)
        mclass = {"track": MediaClass.TRACK, "playlist": MediaClass.PLAYLIST, "album": MediaClass.ALBUM, "artist": MediaClass.ARTIST}.get(media_type, MediaClass.MUSIC)
        mtype = {"track": MediaContentType.TRACK, "playlist": MediaContentType.PLAYLIST, "album": MediaContentType.ALBUM, "artist": MediaContentType.ARTIST}.get(media_type, MediaContentType.MUSIC)
        return BrowseMediaItem(media_id=uri, title=name, artist=artist or None, media_class=mclass, media_type=mtype, can_browse=can_browse, can_play=can_play, thumbnail=image)
