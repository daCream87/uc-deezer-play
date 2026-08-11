from dataclasses import dataclass


@dataclass
class DeezerConfig:
    identifier: str
    name: str
    server_url: str
    access_token: str
    default_player_id: str = ""
    preferred_player_name: str = "Denon AVC-X4800H"
    poll_interval: int = 10
