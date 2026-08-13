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
