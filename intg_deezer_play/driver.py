from ucapi_framework import BaseIntegrationDriver
from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.device import DeezerDevice
from intg_deezer_play.media_player import DeezerMediaPlayer
from intg_deezer_play.remote import DeezerRemote


class DeezerDriver(BaseIntegrationDriver[DeezerDevice, DeezerConfig]):
    def __init__(self):
        super().__init__(device_class=DeezerDevice, entity_classes=[DeezerMediaPlayer, DeezerRemote], driver_id="deezer_music_play")
