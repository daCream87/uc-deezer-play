from __future__ import annotations

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
        self._search_generation = 0
        self._search_debounce_seconds = 0.8
        # Browse items use Music Assistant's canonical URI whenever possible.
        # This survives reconnects/restarts and stays UC-safe.
        self._last_playlist_ref: dict[str, Any] | None = None
        self._open_last_playlist_once = False
        # Track the playlist context of browsed tracks so PLAY_NOW loads the
        # complete selected playlist instead of creating a one-track queue.
        self._playlist_track_context: dict[str, dict[str, str]] = {}
        super().__init__(
            f"media_player.{device_config.identifier}",
            device_config.name,
            features=[
                Features.PLAY_PAUSE,
                Features.STOP,
                Features.PREVIOUS,
                Features.NEXT,
                Features.FAST_FORWARD,
                Features.REWIND,
                Features.DPAD,
                Features.MENU,
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
            options={
                "simple_commands": [
                    "SHUFFLE_TOGGLE",
                    "LAST_PLAYLIST",
                    "ADD_TO_FAVORITES",
                ],
            },
            icon="custom:music-play-logo.png",
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
                Attributes.MEDIA_POSITION: self._device.current_position(),
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
            elif cmd_id == Commands.FAST_FORWARD:
                # Remote 3 lower transport key: next track, not +10s seek.
                ok = await self._device.send("next")
            elif cmd_id == Commands.REWIND:
                # Remote 3 lower transport key: previous track, not -10s seek.
                ok = await self._device.send("previous")
            elif cmd_id == Commands.CURSOR_RIGHT:
                ok = await self._device.send("skip", seconds=10)
            elif cmd_id == Commands.CURSOR_LEFT:
                ok = await self._device.send("skip", seconds=-10)
            elif cmd_id == Commands.CURSOR_UP:
                ok = await self._device.send("next")
            elif cmd_id == Commands.CURSOR_DOWN:
                ok = await self._device.send("previous")
            elif cmd_id == Commands.CURSOR_ENTER:
                ok = await self._device.send("play_pause")
            elif cmd_id == Commands.MENU or cmd_id == "LAST_PLAYLIST":
                # Core does not expose an integration command that can force-open
                # the media browser. Arm a one-shot jump so the next browser
                # request lands directly in the last opened playlist.
                self._open_last_playlist_once = self._last_playlist_ref is not None
                ok = True
            elif cmd_id == "SHUFFLE_TOGGLE":
                ok = await self._device.send(
                    "shuffle",
                    enabled=not self._device.state.shuffle,
                )
            elif cmd_id in ("ADD_TO_FAVORITES", "Add to Favorites"):
                ok = await self._device.send("favorite")
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
                raw_position = p.get("media_position", p.get("position"))
                if raw_position is None:
                    _LOG.error("Seek command missing media_position: %s", p)
                    return StatusCodes.BAD_REQUEST
                ok = await self._device.send(
                    "seek",
                    position=float(raw_position),
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
                raw_id = str(p.get("media_id", "")).strip()
                action = str(
                    p.get("action", MediaPlayAction.PLAY_NOW)
                ).split(".")[-1].upper()

                # Queue browser: selecting an existing queue row must jump to
                # that row, never replace the queue with a new one-track queue.
                if raw_id.startswith("musicplay://queue-item/") and action in {"PLAY_NOW", "PLAY", ""}:
                    try:
                        queue_index = int(raw_id.rsplit("/", 1)[-1])
                    except ValueError:
                        return StatusCodes.BAD_REQUEST
                    ok = await self._device.send("play_index", index=queue_index)
                else:
                    ref = self._decode_ref(raw_id)
                    playable_uri = str(ref.get("uri") or raw_id).strip()

                    if not playable_uri or playable_uri.startswith("musicplay://"):
                        _LOG.error(
                            "PLAY_MEDIA has no playable Music Assistant URI: media_id=%s ref=%s params=%s",
                            raw_id,
                            ref,
                            p,
                        )
                        return StatusCodes.BAD_REQUEST

                    option = {
                        "PLAY_NOW": "play",
                        "PLAY_NEXT": "next",
                        "ADD_TO_QUEUE": "add",
                        "PLAY": "play",
                        "NEXT": "next",
                        "ADD": "add",
                    }.get(action, "play")

                    playlist_context = self._playlist_track_context.get(raw_id)
                    if playlist_context and option == "play":
                        # A track chosen inside a playlist means: load exactly
                        # that playlist and start at the chosen track. This keeps
                        # Next/Previous and Shuffle scoped to the selected list.
                        ok = await self._device.send(
                            "play_playlist",
                            playlist_uri=playlist_context["playlist_uri"],
                            start_item=playlist_context["start_item"],
                        )
                    else:
                        _LOG.info(
                            "PLAY_MEDIA uri=%s option=%s player=%s",
                            playable_uri,
                            option,
                            self._device.state.player_id,
                        )
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


    @staticmethod
    def _paging(options: BrowseOptions, default_limit: int = 20) -> tuple[int, int, int]:
        paging = getattr(options, "paging", None)
        page = max(1, int(getattr(paging, "page", 1) or 1))
        limit = int(getattr(paging, "limit", default_limit) or default_limit)
        limit = max(1, min(limit, 50))
        offset = (page - 1) * limit
        return page, limit, offset

    @staticmethod
    def _pagination(page: int, limit: int, returned: int, offset: int) -> Pagination:
        # Music Assistant library calls do not consistently expose a total.
        # A full page means "there may be another page"; a short page is final.
        count = offset + returned + (1 if returned == limit else 0)
        return Pagination(page=page, limit=limit, count=count)

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
                if self._open_last_playlist_once and self._last_playlist_ref:
                    self._open_last_playlist_once = False
                    return await self._browse_playlist(self._last_playlist_ref, options)

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
                    BrowseMediaItem(
                        media_id="musicplay://radio",
                        title="Radio",
                        media_class=MediaClass.RADIO,
                        can_browse=True,
                        can_search=True,
                        thumbnail="icon://uc:radio",
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
                return await self._browse_queue(options)

            if media_id in {
                "musicplay://playlists",
                "musicplay://tracks",
                "musicplay://albums",
                "musicplay://artists",
                "musicplay://radio",
            }:
                return await self._browse_library(media_id, options)

            ref = self._decode_ref(media_id)
            media_type = str(ref.get("media_type", "")).lower()

            if media_type == "playlist":
                return await self._browse_playlist(ref, options)
            if media_type == "album":
                return await self._browse_album(ref, options)
            if media_type == "artist":
                return await self._browse_artist(ref, options)

            # Provider-specific folders: delegate browsing to Music Assistant.
            page, limit, offset = self._paging(options)
            path = str(ref.get("path") or ref.get("uri") or media_id)
            result = await client.music.browse(path=path)
            rows = getattr(
                result,
                "items",
                result if isinstance(result, list) else [],
            ) or []
            rows = list(rows)
            page_rows = rows[offset: offset + limit]
            items = [self._item(x, "browse") for x in page_rows]
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
                pagination=self._pagination(page, limit, len(items), offset),
            )
        except Exception:
            _LOG.exception("Browse failed: %s", options)
            return StatusCodes.SERVER_ERROR

    async def _browse_library(
        self,
        media_id: str,
        options: BrowseOptions,
    ) -> BrowseResults:
        client = self._device.client
        kind = media_id.rsplit("/", 1)[-1]
        page, limit, offset = self._paging(options)

        methods = {
            "playlists": client.music.get_library_playlists,
            "tracks": client.music.get_library_tracks,
            "albums": client.music.get_library_albums,
            "artists": client.music.get_library_artists,
            "radio": getattr(client.music, "get_library_radios", None),
        }
        method = methods[kind]
        if method is None:
            raise RuntimeError("Installed Music Assistant client does not support radio browsing")

        rows = list(await method(limit=limit, offset=offset) or [])
        items = [self._item(x, kind) for x in rows]
        titles = {
            "playlists": "Wiedergabelisten",
            "tracks": "Titel / Favoriten",
            "albums": "Alben",
            "artists": "Künstler",
            "radio": "Radio",
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
            pagination=self._pagination(page, limit, len(items), offset),
        )

    async def _browse_playlist(
        self,
        ref: dict[str, Any],
        options: BrowseOptions,
    ) -> BrowseResults:
        self._last_playlist_ref = dict(ref)
        item_id = str(ref.get("item_id", ""))
        provider = str(ref.get("provider", "library"))
        page, limit, offset = self._paging(options)

        # Playlist-tracks API uses its own zero-based page. Fetch the provider
        # page, then apply the Remote limit defensively.
        provider_page = max(0, page - 1)
        rows = await self._device._client.command(
            "music/playlists/playlist_tracks",
            item_id=item_id,
            provider_instance_id_or_domain=provider,
            page=provider_page,
        )
        rows = list(rows or [])
        if len(rows) > limit:
            rows = rows[:limit]

        items = [self._item(x, "track") for x in rows]
        playlist_uri = str(ref.get("uri") or "").strip()
        if playlist_uri:
            # Remember each visible playlist track's origin. Music Assistant's
            # start_item accepts the track item id; fall back to its URI.
            for row, item in zip(rows, items):
                track_ref = self._decode_ref(str(item.media_id or ""))
                start_item = str(
                    self._get(row, "item_id", "")
                    or track_ref.get("item_id")
                    or track_ref.get("uri")
                    or item.media_id
                ).strip()
                self._playlist_track_context[str(item.media_id)] = {
                    "playlist_uri": playlist_uri,
                    "start_item": start_item,
                }
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
            pagination=self._pagination(page, limit, len(items), offset),
        )

    async def _browse_album(
        self,
        ref: dict[str, Any],
        options: BrowseOptions,
    ) -> BrowseResults:
        item_id = str(ref.get("item_id", ""))
        provider = str(ref.get("provider", "library"))
        page, limit, offset = self._paging(options)

        client = self._device.client
        getter = getattr(client.music, "get_album_tracks", None)
        if callable(getter):
            rows = await getter(
                item_id=item_id,
                provider_instance_id_or_domain=provider,
            )
        else:
            rows = await self._device._client.command(
                "music/albums/album_tracks",
                item_id=item_id,
                provider_instance_id_or_domain=provider,
            )

        rows = list(rows or [])
        page_rows = rows[offset: offset + limit]
        items = [self._item(x, "track") for x in page_rows]
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
            pagination=self._pagination(page, limit, len(items), offset),
        )

    async def _browse_artist(
        self,
        ref: dict[str, Any],
        options: BrowseOptions,
    ) -> BrowseResults:
        """Artist -> album drilldown, preserving our one-entity UX."""
        client = self._device.client
        item_id = str(ref.get("item_id", ""))
        provider = str(ref.get("provider", "library"))
        page, limit, offset = self._paging(options)

        getter = getattr(client.music, "get_artist_albums", None)
        if not callable(getter):
            raise RuntimeError("Installed Music Assistant client does not support artist albums")

        rows = list(
            await getter(
                item_id=item_id,
                provider_instance_id_or_domain=provider,
            )
            or []
        )
        page_rows = rows[offset: offset + limit]
        items = [self._item(x, "album") for x in page_rows]
        root = BrowseMediaItem(
            media_id=self._encode_ref(ref),
            title=str(ref.get("name") or "Künstler"),
            media_class=MediaClass.ARTIST,
            media_type=MediaContentType.ARTIST,
            can_browse=True,
            can_play=bool(ref.get("uri")),
            thumbnail=self._safe_thumbnail(ref.get("thumbnail")),
            items=items,
        )
        return BrowseResults(
            media=root,
            pagination=self._pagination(page, limit, len(items), offset),
        )

    async def _browse_queue(self, options: BrowseOptions) -> BrowseResults:
        page, limit, offset = self._paging(options)
        rows = await self._device.queue_items(limit=limit, offset=offset)

        current_index = 0
        try:
            queue = await self._device._client.queue(self._device.state.player_id)
            current_index = int(getattr(queue, "current_index", 0) or 0)
        except Exception:
            pass

        items = []
        for local_idx, row in enumerate(rows):
            absolute_idx = offset + local_idx
            media = self._get(row, "media_item", row)
            item = self._item(media, "track")
            item.media_id = f"musicplay://queue-item/{absolute_idx}"
            marker = "▶" if absolute_idx == current_index else f"{absolute_idx + 1:02d}"
            item.title = f"{marker}  {item.title}"
            item.subtitle = item.artist or item.album or None
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
            pagination=self._pagination(page, limit, len(items), offset),
        )

    async def search(
        self,
        options: SearchOptions,
    ) -> SearchResults | StatusCodes:
        client = self._device.client
        if not client:
            return StatusCodes.SERVICE_UNAVAILABLE

        query = str(options.query or "").strip()
        if not query:
            return SearchResults(
                media=[],
                pagination=Pagination(page=1, limit=0, count=0),
            )

        # Remote 3 sends search requests while typing. Debounce locally so only
        # the last query in a burst reaches Music Assistant.
        self._search_generation += 1
        generation = self._search_generation
        await asyncio.sleep(self._search_debounce_seconds)
        if generation != self._search_generation:
            return SearchResults(
                media=[],
                pagination=Pagination(page=1, limit=0, count=0),
            )

        try:
            paging = getattr(options, "paging", None)
            limit = max(1, min(int(getattr(paging, "limit", 50) or 50), 50))

            result = await client.music.search(
                search_query=query,
                limit=limit,
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
                ("radio", "radio"),
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
            _LOG.exception("Search failed: %s", query)
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

        can_browse = media_type in ("playlist", "album", "artist")
        can_play = media_type in ("track", "playlist", "album", "artist", "radio")

        mclass = {
            "track": MediaClass.TRACK,
            "playlist": MediaClass.PLAYLIST,
            "album": MediaClass.ALBUM,
            "artist": MediaClass.ARTIST,
            "radio": MediaClass.RADIO,
        }.get(media_type, MediaClass.MUSIC)

        mtype = {
            "track": MediaContentType.TRACK,
            "playlist": MediaContentType.PLAYLIST,
            "album": MediaContentType.ALBUM,
            "artist": MediaContentType.ARTIST,
            "radio": MediaContentType.RADIO,
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
        """Resolve artwork through MA's canonical schema-31 image proxy."""
        # Direct URLs are fine when Music Assistant already provides one.
        for candidate in (
            self._get(obj, "image_url", None),
            self._get(self._get(obj, "metadata", None), "image_url", None),
        ):
            value = self._safe_thumbnail(candidate)
            if value:
                return value

        # Schema >=31 exposes proxy_id on MediaItemImage. This is the canonical
        # identifier for /imageproxy/<proxy_id>.
        candidates = []
        direct_image = self._get(obj, "image", None)
        if direct_image:
            candidates.append(direct_image)
        metadata = self._get(obj, "metadata", None)
        candidates.extend(self._get(metadata, "images", []) or [])

        for image in candidates:
            proxy_id = self._get(image, "proxy_id", None)
            if proxy_id:
                return (
                    f"{self._device.server_url}/imageproxy/{proxy_id}"
                    "?size=480&fmt=jpg"
                )
            # Older server/client fallback: only use a path if it is already
            # a concrete URL or MA-relative HTTP path.
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
            "radio": "icon://uc:radio",
        }.get(media_type, "icon://uc:music")

    @staticmethod
    def _get(obj: Any, name: str, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _encode_ref(self, data: dict[str, Any]) -> str:
        """Return a persistent UC-safe media id."""
        uri = str(data.get("uri") or "").strip()
        if uri and len(uri) <= 255:
            return uri

        media_type = str(data.get("media_type") or "media").strip()
        provider = str(data.get("provider") or "library").strip()
        item_id = str(data.get("item_id") or "").strip()

        def esc(value: str) -> str:
            return (
                value.replace("%", "%25")
                .replace("/", "%2F")
                .replace("|", "%7C")
            )

        compact = f"musicplay://ref/{esc(media_type)}|{esc(provider)}|{esc(item_id)}"
        if len(compact) > 255:
            compact = f"musicplay://ref/{esc(media_type)}||{esc(item_id)}"
        return compact[:255]

    def _decode_ref(self, value: str) -> dict[str, Any]:
        """Decode a Music Assistant URI or compact Music Play reference."""
        value = str(value or "").strip()
        if not value:
            return {}

        if "://" in value and not value.startswith("musicplay://"):
            provider, rest = value.split("://", 1)
            if "/" in rest:
                media_type, item_id = rest.split("/", 1)
            else:
                media_type, item_id = "", rest
            return {
                "kind": "media",
                "media_type": media_type,
                "item_id": item_id,
                "provider": provider,
                "uri": value,
            }

        prefix = "musicplay://ref/"
        if not value.startswith(prefix):
            return {}

        def unesc(part: str) -> str:
            return (
                part.replace("%7C", "|")
                .replace("%2F", "/")
                .replace("%25", "%")
            )

        parts = value[len(prefix):].split("|", 2)
        while len(parts) < 3:
            parts.append("")
        media_type, provider, item_id = map(unesc, parts)
        uri = (
            f"{provider}://{media_type}/{item_id}"
            if provider and media_type and item_id
            else ""
        )
        return {
            "kind": "media",
            "media_type": media_type,
            "item_id": item_id,
            "provider": provider or "library",
            "uri": uri,
        }
