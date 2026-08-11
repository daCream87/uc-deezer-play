from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow
from intg_deezer_play.config import DeezerConfig


class DeezerSetupFlow(BaseSetupFlow[DeezerConfig]):
    def get_manual_entry_form(self) -> RequestUserInput:
        return RequestUserInput(
            {"en": "Deezer Play Setup", "de": "Deezer Play einrichten"},
            [
                {"id": "name", "label": {"en": "Name", "de": "Name"}, "field": {"text": {"value": "Deezer Play"}}},
                {"id": "server_url", "label": {"en": "Music Assistant URL", "de": "Music-Assistant-URL"}, "field": {"text": {"value": "http://192.168.178.46:8095"}}},
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

        # Important: do not open a Music Assistant websocket inside the UC setup
        # transaction. BaseSetupFlow maps any exception from query_device() to
        # IntegrationSetupError.NOT_FOUND, which makes transient auth/network
        # failures look like a broken integration. The persisted device performs
        # the real authenticated connection after setup completes.

        digest = hashlib.sha1(server_url.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        return DeezerConfig(
            identifier=f"deezer_{digest}", name=name, server_url=server_url,
            access_token=token, preferred_player_name=preferred, poll_interval=10,
        )
