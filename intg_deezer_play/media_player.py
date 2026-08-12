from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ucapi import StatusCodes
from ucapi.api_definitions import Pagination
from ucapi.media_player import (
    Attributes,
    BrowseMediaItem,
    BrowseOptions,
    BrowseResults,
    Commands,
    DeviceClasses,
    Features,
    MediaClass,
    MediaContentType,
    MediaPlayAction,
    MediaPlayer,
    RepeatMode,
    SearchOptions,
    SearchResults,
    States,
)
from ucapi_framework import MediaPlayerEntity

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.device import DeezerDevice

_LOG = logging.getLogger(__name__)


class DeezerMediaPlayer(MediaPlayerEntity):
    """Single native UC MediaPlayer entity for Music Assistant."""

    def __init__(self, device_config: DeezerConfig, device: DeezerDevice):
        self._device = device
        super().__init__(
            f"media_player.{device_config.identifier}",
            device_config.name,
            features=[
                Features.PLAY_PAUSE,
                Features.STOP,
                Features.PREVIOUS,
                Features.NEXT,
                Features.VOLUME,
                Features.VOLUME_UP_DOWN,
                Features.MUTE_TOGGLE,
                Features.SHUFFLE,
                Features.REPEAT,
                Features.SEEK,
                Features.MEDIA_DURATION,
                Features.MEDIA_POSITION,
                Features.MEDIA_TITLE,
                Features.MEDIA_ARTIST,
                Features.MEDIA_ALBUM,
                Features.MEDIA_IMAGE_URL,
                Features.SELECT_SOURCE,
                Features.PLAY_MEDIA,
                Features.PLAY_MEDIA_ACTION,
                Features.CLEAR_PLAYLIST,
                Features.BROWSE_MEDIA,
                Features.SEARCH_MEDIA,
                Features.SEARCH_MEDIA_CLASSES,
            ],
            attributes={
                Attributes.STATE: States.UNKNOWN,
                Attributes.PLAY_MEDIA_ACTION: [
                    MediaPlayAction.PLAY_NOW,
                    MediaPlayAction.PLAY_NEXT,
                    MediaPlayAction.ADD_TO_QUEUE,
                ],
                Attributes.SEARCH_MEDIA_CLASSES: [
                    MediaClass.TRACK,
                    MediaClass.ALBUM,
                    MediaClass.ARTIST,
                    MediaClass.PLAYLIST,
                ],
            },
            device_class=DeviceClasses.RECEIVER,
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        state = self._device.state
        if not state.online:
            self.update({Attributes.STATE: States.UNAVAILABLE})
            return

        raw = state.state.upper()
        if "PLAY" in raw:
            uc_state = States.PLAYING
        elif "PAUSE" in raw:
            uc_state = States.PAUSED
        else:
            uc_state = States.ON

        self.update(
            {
                Attributes.STATE: uc_state,
                Attributes.VOLUME: state.volume,
                Attributes.MUTED: state.muted,
                Attributes.MEDIA_TITLE: state.title,
                Attributes.MEDIA_ARTIST: state.artist,
                Attributes.MEDIA_ALBUM: state.album,
                Attributes.MEDIA_DURATION: state.duration,
                Attributes.MEDIA_POSITION: state.position,
                Attributes.MEDIA_POSITION_UPDATED_AT: datetime.now(
                    timezone.utc
                ).isoformat(),
                Attributes.MEDIA_IMAGE_URL: state.image_url,
                Attributes.MEDIA_ID: state.media_id,
                Attributes.MEDIA_PLAYLIST: state.playlist,
                Attributes.SHUFFLE: state.shuffle,
                Attributes.REPEAT: (
                    state.repeat if state.repeat in ("OFF", "ALL", "ONE") else "OFF"
                ),
                Attributes.SOURCE: state.player_name,
                Attributes.SOURCE_LIST: [name for _, name in state.players],
                Attributes.PLAY_MEDIA_ACTION: [
                    MediaPlayAction.PLAY_NOW,
                    MediaPlayAction.PLAY_NEXT,
                    MediaPlayAction.ADD_TO_QUEUE,
                ],
                Attributes.SEARCH_MEDIA_CLASSES: [
                    MediaClass.TRACK,
                    MediaClass.ALBUM,
                    MediaClass.ARTIST,
                    MediaClass.PLAYLIST,
                ],
            }
        )

    async def _handle_command(
        self,
        entity: MediaPlayer,
        cmd_id: str,
        params: dict[str, Any] | None = None,
    ) -> StatusCodes:
        p = params or {}
        try:
            if cmd_id == Commands.PLAY_PAUSE:
                ok = await self._device.send("play_pause")
            elif cmd_id == Commands.STOP:
                ok = await self._device.send("stop")
            elif cmd_id == Commands.NEXT:
                ok = await self._device.send("next")
            elif cmd_id == Commands.PREVIOUS:
                ok = await self._device.send("previous")
            elif cmd_id == Commands.VOLUME_UP:
                ok = await self._device.send("volume_up")
            elif cmd_id == Commands.VOLUME_DOWN:
                ok = await self._device.send("volume_down")
            elif cmd_id == Commands.MUTE_TOGGLE:
                ok = await self._device.send("mute_toggle")
            elif cmd_id == Commands.VOLUME:
                ok = await self._device.send(
                    "volume",
                    volume=p.get("volume", 0),
                )
            elif cmd_id == Commands.SEEK:
                ok = await self._device.send(
                    "seek",
                    position=p.get(
                        "media_position",
                        p.get("position", 0),
                    ),
                )
            elif cmd_id == Commands.SHUFFLE:
                ok = await self._device.send(
                    "shuffle",
                    enabled=p.get("shuffle", False),
                )
            elif cmd_id == Commands.REPEAT:
                ok = await self._device.send(
                    "repeat",
                    mode=p.get("repeat", RepeatMode.OFF),
                )
            elif cmd_id == Commands.SELECT_SOURCE:
                ok = await self._device.select_player(
                    str(p.get("source", ""))
                )
            elif cmd_id == Commands.CLEAR_PLAYLIST:
                ok = await self._device.send("clear_queue")
            elif cmd_id == Commands.PLAY_MEDIA:
                raw_id = str(p.get("media_id", ""))
                ref = self._decode_ref(raw_id)
                playable_uri = str(ref.get("uri") or raw_id)
                action = str(
                    p.get("action", MediaPlayAction.PLAY_NOW)
                ).upper()
                option = {
                    MediaPlayAction.PLAY_NOW: "play",
                    MediaPlayAction.PLAY_NEXT: "next",
                    MediaPlayAction.ADD_TO_QUEUE: "add",
                    "PLAY_NOW": "play",
                    "PLAY_NEXT": "next",
                    "ADD_TO_QUEUE": "add",
                }.get(action, "play")
                ok = await self._device.send(
                    "play_media",
                    media_id=playable_uri,
                    option=option,
                )
            else:
                return StatusCodes.NOT_IMPLEMENTED

            return StatusCodes.OK if ok else StatusCodes.BAD_REQUEST
        except Exception:
            _LOG.exception("UC media command failed: %s", cmd_id)
            return StatusCodes.SERVER_ERROR

    async def browse(
        self,
        options: BrowseOptions,
    ) -> BrowseResults | StatusCodes:
        client = self._device.client
        if not client:
            return StatusCodes.SERVICE_UNAVAILABLE

        try:
            media_id = options.media_id or "root"

            if media_id == "root":
                items = [
                    BrowseMediaItem(
                        media_id="musicplay://queue",
                        title="Warteschlange",
                        subtitle="Aktuelle Abspielreihenfolge",
                        media_class=MediaClass.PLAYLIST,
                        can_browse=True,
                        thumbnail="icon://uc:playlist",
                    ),
                    BrowseMediaItem(
                        media_id="musicplay://playlists",
                        title="Wiedergabelisten",
                        subtitle="Playlists aus Music Assistant",
                        media_class=MediaClass.DIRECTORY,
                        can_browse=True,
                        can_search=True,
                        thumbnail="icon://uc:playlist",
                    ),
                    BrowseMediaItem(
                        media_id="musicplay://tracks",
                        title="Titel / Favoriten",
                        media_class=MediaClass.DIRECTORY,
                        can_browse=True,
                        can_search=True,
                        thumbnail="icon://uc:favorite",
                    ),
                    BrowseMediaItem(
                        media_id="musicplay://albums",
                        title="Alben",
                        media_class=MediaClass.DIRECTORY,
                        can_browse=True,
                        can_search=True,
                        thumbnail="icon://uc:album",
                    ),
                    BrowseMediaItem(
                        media_id="musicplay://artists",
                        title="Künstler",
                        media_class=MediaClass.DIRECTORY,
                        can_browse=True,
                        can_search=True,
                        thumbnail="icon://uc:artist",
                    ),
                ]
                root = BrowseMediaItem(
                    media_id="root",
                    title="Music Play",
                    subtitle=self._device.state.player_name or None,
                    media_class=MediaClass.MUSIC,
                    can_browse=True,
                    can_search=True,
                    thumbnail="icon://uc:music",
                    items=items,
                )
                return BrowseResults(
                    media=root,
                    pagination=Pagination(
                        page=1,
                        limit=len(items),
                        count=len(items),
                    ),
                )

            if media_id == "musicplay://queue":
                return await self._browse_queue()

            if media_id in {
                "musicplay://playlists",
                "musicplay://tracks",
                "musicplay://albums",
                "musicplay://artists",
            }:
                return await self._browse_library(media_id)

            ref = self._decode_ref(media_id)
            media_type = str(ref.get("media_type", "")).lower()

            if media_type == "playlist":
                return await self._browse_playlist(ref)

            if media_type == "album":
                return await self._browse_album(ref)

            # Provider-aware fallback for folders returned by Music Assistant.
            path = str(ref.get("path") or ref.get("uri") or media_id)
            result = await client.music.browse(path=path)
            rows = getattr(
                result,
                "items",
                result if isinstance(result, list) else [],
            ) or []
            items = [self._item(x, "browse") for x in rows]
            root = BrowseMediaItem(
                media_id=media_id,
                title=getattr(result, "name", "Music"),
                media_class=MediaClass.DIRECTORY,
                can_browse=True,
                can_search=True,
                items=items,
            )
            return BrowseResults(
                media=root,
                pagination=Pagination(
                    page=1,
                    limit=len(items),
                    count=len(items),
                ),
            )
        except Exception:
            _LOG.exception("Browse failed: %s", options)
            return StatusCodes.SERVER_ERROR

    async def _browse_library(self, media_id: str) -> BrowseResults:
        client = self._device.client
        kind = media_id.rsplit("/", 1)[-1]
        method = {
            "playlists": client.music.get_library_playlists,
            "tracks": client.music.get_library_tracks,
            "albums": client.music.get_library_albums,
            "artists": client.music.get_library_artists,
        }[kind]

        rows = await method(limit=100, offset=0)
        items = [self._item(x, kind) for x in rows]
        titles = {
            "playlists": "Wiedergabelisten",
            "tracks": "Titel / Favoriten",
            "albums": "Alben",
            "artists": "Künstler",
        }

        root = BrowseMediaItem(
            media_id=media_id,
            title=titles[kind],
            media_class=MediaClass.DIRECTORY,
            can_browse=True,
            can_search=True,
            items=items,
        )
        return BrowseResults(
            media=root,
            pagination=Pagination(
                page=1,
                limit=len(items),
                count=len(items),
            ),
        )

    async def _browse_playlist(self, ref: dict[str, Any]) -> BrowseResults:
        item_id = str(ref.get("item_id", ""))
        provider = str(ref.get("provider", "library"))
        rows = await self._device._client.command(
            "music/playlists/playlist_tracks",
            item_id=item_id,
            provider_instance_id_or_domain=provider,
            page=0,
        )
        items = [self._item(x, "track") for x in (rows or [])]
        root = BrowseMediaItem(
            media_id=self._encode_ref(ref),
            title=str(ref.get("name") or "Wiedergabeliste"),
            subtitle="Titel auswählen: Jetzt / Als Nächstes / Zur Queue",
            media_class=MediaClass.PLAYLIST,
            media_type=MediaContentType.PLAYLIST,
            can_browse=True,
            can_play=bool(ref.get("uri")),
            can_search=False,
            thumbnail=self._safe_thumbnail(ref.get("thumbnail")),
            items=items,
        )
        return BrowseResults(
            media=root,
            pagination=Pagination(
                page=1,
                limit=len(items),
                count=len(items),
            ),
        )

    async def _browse_album(self, ref: dict[str, Any]) -> BrowseResults:
        item_id = str(ref.get("item_id", ""))
        provider = str(ref.get("provider", "library"))
        rows = await self._device._client.command(
            "music/albums/album_tracks",
            item_id=item_id,
            provider_instance_id_or_domain=provider,
        )
        items = [self._item(x, "track") for x in (rows or [])]
        root = BrowseMediaItem(
            media_id=self._encode_ref(ref),
            title=str(ref.get("name") or "Album"),
            media_class=MediaClass.ALBUM,
            media_type=MediaContentType.ALBUM,
            can_browse=True,
            can_play=bool(ref.get("uri")),
            thumbnail=self._safe_thumbnail(ref.get("thumbnail")),
            items=items,
        )
        return BrowseResults(
            media=root,
            pagination=Pagination(
                page=1,
                limit=len(items),
                count=len(items),
            ),
        )

    async def _browse_queue(self) -> BrowseResults:
        rows = await self._device.queue_items(limit=100, offset=0)
        current_index = 0
        queue = None
        try:
            queue = await self._device._client.queue(
                self._device.state.player_id
            )
            current_index = int(
                getattr(queue, "current_index", 0)
                if queue is not None
                else 0
            )
        except Exception:
            pass

        items = []
        for idx, row in enumerate(rows):
            media = self._get(row, "media_item", row)
            item = self._item(media, "track")
            marker = "▶" if idx == current_index else f"{idx + 1:02d}"
            item.title = f"{marker}  {item.title}"
            item.subtitle = item.artist or item.album or None
            # Queue entries are shown as a transparent ordering view.
            item.can_browse = False
            items.append(item)

        root = BrowseMediaItem(
            media_id="musicplay://queue",
            title="Warteschlange",
            subtitle="Reihenfolge der ausgewählten Titel",
            media_class=MediaClass.PLAYLIST,
            can_browse=True,
            items=items,
        )
        return BrowseResults(
            media=root,
            pagination=Pagination(
                page=1,
                limit=len(items),
                count=len(items),
            ),
        )

    async def search(
        self,
        options: SearchOptions,
    ) -> SearchResults | StatusCodes:
        client = self._device.client
        if not client:
            return StatusCodes.SERVICE_UNAVAILABLE

        try:
            result = await client.music.search(
                search_query=options.query,
                limit=50,
            )

            wanted = None
            if options.filter and options.filter.media_classes:
                wanted = {
                    str(x).lower().split(".")[-1]
                    for x in options.filter.media_classes
                }

            rows = []
            for attr, media_type in (
                ("tracks", "track"),
                ("playlists", "playlist"),
                ("albums", "album"),
                ("artists", "artist"),
            ):
                if wanted and media_type not in wanted:
                    continue
                rows.extend(getattr(result, attr, []) or [])

            items = [self._item(x, "search") for x in rows]
            return SearchResults(
                media=items,
                pagination=Pagination(
                    page=1,
                    limit=len(items),
                    count=len(items),
                ),
            )
        except Exception:
            _LOG.exception("Search failed: %s", options.query)
            return StatusCodes.SERVER_ERROR

    def _item(self, obj: Any, kind: str) -> BrowseMediaItem:
        media_type = str(
            self._get(obj, "media_type", kind)
        ).lower().split(".")[-1]

        name = str(self._get(obj, "name", "Unbenannt") or "Unbenannt")
        uri = str(
            self._get(
                obj,
                "uri",
                self._get(obj, "item_id", ""),
            )
            or ""
        )
        item_id = str(self._get(obj, "item_id", "") or "")
        provider = str(
            self._get(
                obj,
                "provider",
                self._get(obj, "provider_domain", "library"),
            )
            or "library"
        )

        artists = self._get(obj, "artists", []) or []
        artist = ", ".join(
            str(self._get(a, "name", a))
            for a in artists
        )
        if not artist:
            artist = str(self._get(obj, "artist", "") or "")

        album_obj = self._get(obj, "album", None)
        album = str(
            self._get(
                album_obj,
                "name",
                self._get(obj, "album_name", ""),
            )
            or ""
        )

        thumbnail = self._extract_artwork(obj)

        can_browse = media_type in ("playlist", "album")
        can_play = media_type in ("track", "playlist", "album", "artist")

        mclass = {
            "track": MediaClass.TRACK,
            "playlist": MediaClass.PLAYLIST,
            "album": MediaClass.ALBUM,
            "artist": MediaClass.ARTIST,
        }.get(media_type, MediaClass.MUSIC)

        mtype = {
            "track": MediaContentType.TRACK,
            "playlist": MediaContentType.PLAYLIST,
            "album": MediaContentType.ALBUM,
            "artist": MediaContentType.ARTIST,
        }.get(media_type, MediaContentType.MUSIC)

        ref = {
            "kind": "media",
            "media_type": media_type,
            "item_id": item_id,
            "provider": provider,
            "uri": uri,
            "name": name,
            "thumbnail": thumbnail,
        }

        return BrowseMediaItem(
            media_id=self._encode_ref(ref),
            title=name,
            subtitle=album or None,
            artist=artist or None,
            album=album or None,
            media_class=mclass,
            media_type=mtype,
            can_browse=can_browse,
            can_play=can_play,
            thumbnail=thumbnail or self._fallback_icon(media_type),
            duration=int(self._get(obj, "duration", 0) or 0) or None,
        )

    def _extract_artwork(self, obj: Any) -> str | None:
        # Use only concrete URLs surfaced by MA/model objects.
        for candidate in (
            self._get(obj, "image_url", None),
            self._get(self._get(obj, "image", None), "path", None),
            self._get(self._get(obj, "metadata", None), "image_url", None),
        ):
            value = self._safe_thumbnail(candidate)
            if value:
                return value

        metadata = self._get(obj, "metadata", None)
        images = self._get(metadata, "images", []) or []
        for image in images:
            path = self._get(image, "path", None)
            value = self._safe_thumbnail(path)
            if value:
                return value
        return None

    def _safe_thumbnail(self, value: Any) -> str | None:
        if not value:
            return None
        value = str(value).strip()
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith("/"):
            return self._device.absolute_image_url(value)
        if value.startswith("icon://uc:"):
            return value
        return None

    @staticmethod
    def _fallback_icon(media_type: str) -> str:
        return {
            "track": "icon://uc:music",
            "playlist": "icon://uc:playlist",
            "album": "icon://uc:album",
            "artist": "icon://uc:artist",
        }.get(media_type, "icon://uc:music")

    @staticmethod
    def _get(obj: Any, name: str, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @staticmethod
    def _encode_ref(data: dict[str, Any]) -> str:
        raw = json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"musicplay://ref/{token}"

    @staticmethod
    def _decode_ref(value: str) -> dict[str, Any]:
        prefix = "musicplay://ref/"
        if not value.startswith(prefix):
            return {}
        token = value[len(prefix):]
        token += "=" * (-len(token) % 4)
        try:
            return json.loads(
                base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
            )
        except Exception:
            return {}
