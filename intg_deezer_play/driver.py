from ucapi_framework import BaseIntegrationDriver
from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.device import DeezerDevice
from intg_deezer_play.media_player import DeezerMediaPlayer


class DeezerDriver(BaseIntegrationDriver[DeezerDevice, DeezerConfig]):
    def __init__(self):
        # Only expose the native media_player. The former helper RemoteEntity
        # caused a second visible "... Tasten" device. Media playback, browse,
        # artwork and status are all handled by the media_player entity.
        super().__init__(
            device_class=DeezerDevice,
            entity_classes=[DeezerMediaPlayer],
            driver_id="music_play",
        )

    async def on_r2_enter_standby(self) -> None:
        """Keep the device connection alive but reduce background polling.

        The framework normally disconnects devices on display standby. We keep
        the existing connection/session to avoid wake reconnect problems, while
        increasing the polling interval to reduce LAN traffic and background work.
        """
        _LOG.debug("Enter standby: keeping Music Assistant connection alive, poll interval -> 30s")
        for device in self._device_instances.values():
            device._poll_interval = 30

    async def on_r2_exit_standby(self) -> None:
        """Restore the normal polling interval without reconnecting the device."""
        _LOG.debug("Exit standby: connection kept alive, poll interval -> 10s")
        for device in self._device_instances.values():
            device._poll_interval = 10
