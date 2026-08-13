import logging

from ucapi_framework import BaseIntegrationDriver
from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.device import DeezerDevice
from intg_deezer_play.media_player import DeezerMediaPlayer


_LOG = logging.getLogger(__name__)


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
        """Keep the Music Assistant connection alive while Remote 3 sleeps.

        ucapi-framework disconnects all device instances on ENTER_STANDBY by
        default. For Music Play this tears down the Music Assistant websocket,
        event subscription and local position ticker on every display sleep.
        The integration process itself remains alive, so deliberately keep the
        existing connection and polling tasks running.
        """
        _LOG.debug("Enter standby event: keeping Music Assistant connection alive")
        # Intentionally do NOT call super().on_r2_enter_standby().

    async def on_r2_exit_standby(self) -> None:
        """Do not reconnect a Music Assistant client that stayed alive.

        Avoiding the framework's default reconnect prevents a second websocket
        lifecycle from racing with the still-active listener after display wake.
        Normal PollingDevice recovery remains responsible for genuine network or
        server outages.
        """
        _LOG.debug("Exit standby event: Music Assistant connection was kept alive")
        # Intentionally do NOT call super().on_r2_exit_standby().
