# Related projects and clean-room implementation note

Music Play is an independent community integration for Unfolded Circle Remote 3.

During development of version 0.3.0, the public project
[`jackjpowell/uc-intg-musicassistant`](https://github.com/jackjpowell/uc-intg-musicassistant)
was reviewed as a compatibility and feature reference. That project is published
under the Mozilla Public License 2.0 (MPL-2.0).

No source file from that project is included in Music Play v0.3.0 and no source
file was copied verbatim into this repository. The new Music Play functionality
was implemented independently against the public Music Assistant client API,
the Unfolded Circle integration API, and the established architecture already
used by Music Play.

Ideas confirmed as useful by comparing the projects include:

- Music Assistant mDNS discovery via `_mass._tcp.local.`
- paginated library browsing
- radio-library browsing
- artist -> album -> track navigation
- adding the currently playing item to Music Assistant favorites

The implementations in Music Play intentionally preserve Music Play's different
Remote-3 UX: one visible media-player entity, selectable playback device, queue
ordering, debounced search, Remote-specific DPAD controls, local progress
tracking and standby/reconnect handling.

The original project's copyright and MPL-2.0 license remain with its authors.
This notice is provided for transparency and attribution; it does not import
the original project's MPL-licensed source into Music Play.

Additional v0.3.1 note:
Music Play's username/password login uses the official `music-assistant-client`
`login_with_token()` helper documented by Music Assistant. This was implemented
directly against the public client API and is not copied from the related
MPL-2.0 Remote 3 integration.
