from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.ma_client import create_long_lived_token

_LOG = logging.getLogger(__name__)


class DeezerSetupFlow(BaseSetupFlow[DeezerConfig]):
    def get_manual_entry_form(self) -> RequestUserInput:
        return RequestUserInput(
            {"en": "Music Play Setup", "de": "Music Play einrichten"},
            [
                {
                    "id": "name",
                    "label": {"en": "Name", "de": "Name"},
                    "field": {"text": {"value": "Music Play"}},
                },
                {
                    "id": "server_url",
                    "label": {
                        "en": "Music Assistant URL",
                        "de": "Music-Assistant-URL",
                    },
                    "field": {
                        "text": {"value": "http://192.168.178.46:8095"}
                    },
                },
                {
                    "id": "access_token",
                    "label": {
                        "en": "Long-lived access token (optional)",
                        "de": "Long-Lived Access Token (optional)",
                    },
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "username",
                    "label": {
                        "en": "Music Assistant username (optional)",
                        "de": "Music-Assistant-Benutzername (optional)",
                    },
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "password",
                    "label": {
                        "en": "Music Assistant password (optional)",
                        "de": "Music-Assistant-Passwort (optional)",
                    },
                    # UC's generic text input is used for maximum firmware
                    # compatibility. The password is never stored in DeezerConfig.
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "preferred_player_name",
                    "label": {
                        "en": "Preferred player",
                        "de": "Bevorzugter Player",
                    },
                    "field": {"text": {"value": "Denon AVC-X4800H"}},
                },
            ],
        )

    async def query_device(self, input_values: dict[str, Any]) -> DeezerConfig:
        name = str(
            input_values.get("name")
            or input_values.get("device_name")
            or "Music Play"
        ).strip() or "Music Play"

        server_url = str(
            input_values.get("server_url")
            or input_values.get("address")
            or ""
        ).strip().rstrip("/")

        access_token = str(input_values.get("access_token", "")).strip()
        username = str(input_values.get("username", "")).strip()
        password = str(input_values.get("password", "")).strip()
        preferred = str(
            input_values.get("preferred_player_name", "")
        ).strip()

        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "Enter a valid Music Assistant URL, "
                "e.g. http://192.168.178.20:8095"
            )

        # Existing token remains the most robust path and avoids a network
        # transaction during setup. If no token is supplied, authenticate once
        # with Music Assistant and create a dedicated long-lived token.
        if not access_token:
            if not username or not password:
                raise ValueError(
                    "Enter either a Long-Lived Access Token or "
                    "Music Assistant username and password."
                )
            try:
                access_token = await create_long_lived_token(
                    server_url,
                    username,
                    password,
                )
            except Exception as err:
                _LOG.exception(
                    "Music Assistant login/token creation failed"
                )
                raise ValueError(
                    "Music Assistant login failed. "
                    "Check server URL, username and password."
                ) from err

        # Only the resulting token is persisted. Username/password are not part
        # of DeezerConfig and are therefore not stored for later connections.
        digest = hashlib.sha1(
            server_url.encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()[:10]

        return DeezerConfig(
            identifier=f"music_{digest}",
            name=name,
            server_url=server_url,
            access_token=access_token,
            preferred_player_name=preferred,
            poll_interval=10,
        )
