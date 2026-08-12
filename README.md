# Music Play for Unfolded Circle Remote 3

Version 0.2.0 source build based on the proven packaging/runtime architecture of the Philips Titan OS Remote 3 integration, with all Philips-specific communication removed.


## v0.2.0 setup fix

- Removes the Music Assistant websocket/API validation from inside the UC setup transaction.
- The setup form now stores URL/token first; the normal device lifecycle performs the authenticated MA connection afterwards.
- Default Music Assistant URL is prefilled for the current installation as `http://192.168.178.46:8095`.
- Keeps the Titan-derived package layout and integration ID unchanged.

## Architecture

Remote 3 -> Music Play integration -> local Music Assistant -> Deezer music provider + playback player (recommended: Denon AVC-X4800H via HEOS).

Home Assistant is not required.

## v0.2.0 scope

- Native UC media-player entity with dynamic Now Playing metadata and album artwork URL
- Play/Pause, Stop, Previous, Next
- Volume, volume up/down and mute of the selected playback player
- Seek, Shuffle, Repeat
- Player selection from Music Assistant players
- Library browse for playlists, favourite/library tracks, albums and artists
- Search and Play Media
- Physical Remote 3 transport/volume buttons through a companion Remote entity
- Event-triggered state refresh plus 10-second low-frequency fallback polling
- Automatic reconnect handled by the ucapi-framework device lifecycle plus MA reconnect
- Persistent Remote configuration
- Titan-derived AArch64 GitHub Actions packaging structure

## Requirements

1. A Music Assistant Server reachable from Remote 3 on the LAN.
2. Deezer configured as a Music Provider in Music Assistant.
3. Denon AVC-X4800H available as a HEOS player in Music Assistant.
4. A Music Assistant Long-Lived Access Token created in the Music Assistant profile.

Default Music Assistant port: 8095.

## Setup on Remote 3

Enter:
- Name: `Music Play`
- Music Assistant URL, e.g. `http://192.168.178.20:8095`
- Long-Lived Access Token
- Preferred player: `Denon AVC-X4800H` (the integration also tries Denon/HEOS/X4800H automatically)

## Cover art

Album artwork is passed to UC as a dynamic `media_image_url` from the current Music Assistant media object. No custom per-track PNG assets are used.

## Notes

- This project does not implement or invent a Deezer Connect protocol.
- Flow is intentionally not hard-coded into v0.1.0. It should be added only after the chosen Music Assistant/Deezer provider exposes a stable, verified Flow browse/play entry.
- Alexa output is intentionally deferred because the current Music Assistant Alexa player provider is experimental; the player abstraction is already designed so it can be exposed later if it appears in Music Assistant.
- The source ZIP is intended for GitHub Actions AArch64 packaging. The workflow creates the Remote-3 `.tar.gz` artifact in the same proven root layout as the Titan project.


## v0.2.0 connection/setup fix
- Fresh Remote 3 driver ID `deezer_music_play` to avoid stale icon/config association.
- Music Assistant listener now waits for authenticated initial state before polling players.
- Existing Titan-derived package layout remains unchanged.


## v0.2.0 setup/device fix
- Implements the mandatory `PollingDevice.log_id` property in `DeezerDevice`.
- Fixes `Can't instantiate abstract class DeezerDevice with abstract method log_id`.
- No changes to Music Assistant URL/token handling, HEOS player logic, or package layout.

## v0.2.0
- Visible integration name changed to **Music Play**.
- New driver ID `music_play`.
- Removed the second visible helper RemoteEntity (`... Tasten`); only the native media-player is exposed.
- Fixed Music Assistant connection compatibility by removing the unsupported `locale=` constructor argument.
- Added startup compatibility for Music Assistant client releases with and without `init_ready`.
- Music Play is provider-agnostic: Deezer, Tidal, Spotify and other sources configured in Music Assistant can be browsed/played through the same integration where supported by Music Assistant.

## v0.2.0 multimedia / browse update
- Native Remote 3 media browser with playlists, library tracks, albums, artists and current queue.
- Native search for tracks, playlists, albums and artists.
- Play actions: Play now, Play next, Add to queue.
- Queue view numbers items in playback order.
- Clear queue support.
- Improved Now Playing artwork: prefer Music Assistant Player.current_media.image_url and resolve MA-relative URLs.
- Keeps a single visible MediaPlayer entity; no second helper "Tasten" device.
- Playback controls remain native media-player features: Play/Pause, Stop, Previous, Next, volume, mute, seek, shuffle and repeat.
