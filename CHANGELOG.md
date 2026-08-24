# Changelog

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

