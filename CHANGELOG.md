# Changelog

## v0.3.1

### Added
- **Power button:** stops the active Music Assistant queue and then powers off / puts the selected playback device into standby when supported.
- **Stop button:** explicitly stops the active Music Assistant playback queue without powering off the player.
- **Simplified login:** setup accepts either an existing Long-Lived Access Token or Music Assistant username/password. With credentials, Music Play creates a dedicated Long-Lived Token and stores only the token.
- **Automatic GitHub Release:** pushing a matching `v*` tag now builds, validates and publishes the exact Remote-3 `.tar.gz` package as a GitHub Release asset. Manual workflow runs continue to build artifacts without publishing a Release.

