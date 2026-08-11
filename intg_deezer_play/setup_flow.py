from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow
from music_assistant_client import MusicAssistantClient

from intg_deezer_play.config import DeezerConfig


class DeezerSetupFlow(BaseSetupFlow[DeezerConfig]):
    def get_manual_entry_form(self) -> RequestUserInput:
        return RequestUserInput(
            {"en": "Deezer Play Setup", "de": "Deezer Play einrichten"},
            [
                {"id": "name", "label": {"en": "Name", "de": "Name"}, "field": {"text": {"value": "Deezer Play"}}},
                {"id": "server_url", "label": {"en": "Music Assistant URL", "de": "Music-Assistant-URL"}, "field": {"text": {"value": "http://music-assistant.local:8095"}}},
                {"id": "access_token", "label": {"en": "Long-lived access token", "de": "Long-Lived Access Token"}, "field": {"text": {"value": ""}}},
                {"id": "preferred_player_name", "label": {"en": "Preferred player", "de": "Bevorzugter Player"}, "field": {"text": {"value": "Denon AVC-X4800H"}}},
            ],
        )

    async def query_device(self, input_values: dict[str, Any]) -> DeezerConfig:
        name = str(input_values.get("name", "Deezer Play")).strip() or "Deezer Play"
        server_url = str(input_values.get("server_url", "")).strip().rstrip("/")
        token = str(input_values.get("access_token", "")).strip()
        preferred = str(input_values.get("preferred_player_name", "")).strip()
        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Enter a valid Music Assistant URL, e.g. http://192.168.178.20:8095")
        if not token:
            raise ValueError("A Music Assistant long-lived access token is required")

        # Validate authentication without keeping a second setup session alive.
        try:
            client = MusicAssistantClient(server_url, None, token=token)
            await client.__aenter__()
            try:
                await client.send_command("players/all")
            finally:
                await client.__aexit__(None, None, None)
        except Exception as err:
            raise ValueError(f"Music Assistant connection failed: {type(err).__name__}: {err}") from err

        digest = hashlib.sha1(server_url.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        return DeezerConfig(
            identifier=f"deezer_{digest}", name=name, server_url=server_url,
            access_token=token, preferred_player_name=preferred, poll_interval=10,
        )
