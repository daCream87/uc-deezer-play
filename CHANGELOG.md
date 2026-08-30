# Changelog

## v0.3.5

### Changed
- The Remote 3 **list/media-browser button** now opens the currently active Music Assistant queue directly instead of always opening the Music Play overview.
- The browser automatically jumps to the queue page containing the currently playing track.
- The currently playing track is clearly marked with `▶` and `Läuft gerade`.
- The queue title uses Music Assistant's current `PlayerQueue.sources` information when available, so a running playlist/source can be shown by name.
- A **Musikübersicht** entry inside the current queue provides access back to Playlists, Albums, Artists, Favorites, Search and Radio.
- If no active queue exists, the list button falls back to the normal Music Play overview.

### Compatibility
- Updated queue handling for current Music Assistant clients: `get_active_queue(player_id)` is preferred and the actual `queue_id` is used for queue browsing and queue commands. This improves grouped/synced player handling where `queue_id` can differ from `player_id`.

## v0.3.4

### Fixed
- Remote 3 lower transport **Next/Previous** keys now change tracks instead of seeking ±10 seconds; DPAD left/right keeps ±10-second seek.
- Selecting a track inside a playlist now loads the complete selected playlist and starts at that track instead of creating a one-track queue.
- Playlist playback explicitly uses a finite queue (`radio_mode=False`) and replaces stale queue contents, so normal Shuffle stays inside the selected playlist.
- Selecting a title in the queue browser now jumps to that existing queue index instead of replacing the queue with a single track.
- Normal queue Shuffle is preserved when a playlist is loaded.


## v0.3.3

### Fixed
- Fixed the discovered-device setup flow. Selecting an automatically discovered Music Assistant server now opens the authentication screen instead of immediately failing with `NOT_FOUND`.
- Setup flow is now explicitly: **discover/select server → login screen → validate credentials/token → save configuration**.
- Music Assistant username/password can be used to create a dedicated long-lived `Music Play Remote 3` token; only the resulting token is stored.
- Existing Long-Lived Access Token entry remains supported.
- The resulting token is validated against Music Assistant before the setup is saved.
- Corrected the internal startup version string so it matches `driver.json`.

## v0.3.2

### Fixed
- Fixed the Remote 3 startup crash `AttributeError: POWER`. `POWER` is not a valid media-player feature/command in the bundled UC API used by this integration.
- Physical **Power** is now mapped safely through the Remote entity as `POWER_TOGGLE`: it stops Music Assistant playback and then powers off / puts the selected player into standby when supported.
- Physical **Stop** remains independent and stops playback only.
- Updated GitHub Actions validation so an unsupported media-player `POWER` enum cannot accidentally be reintroduced.

## v0.3.1

### Added
- **Fully automatic release:** a new version committed to `main` automatically creates its `v<version>` tag, GitHub Release and installable AArch64 `.tar.gz` asset after a successful build. Existing version tags are not duplicated.
- **Power button:** stops the active Music Assistant queue and then powers off / puts the selected playback device into standby when supported.
- **Stop button:** explicitly stops the active Music Assistant playback queue without powering off the player.
- **Simplified login:** setup accepts either an existing Long-Lived Access Token or Music Assistant username/password. With credentials, Music Play creates a dedicated Long-Lived Token and stores only the token.
- **Automatic GitHub Release:** pushing a matching `v*` tag now builds, validates and publishes the exact Remote-3 `.tar.gz` package as a GitHub Release asset. Manual workflow runs continue to build artifacts without publishing a Release.

