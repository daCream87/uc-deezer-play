from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

from ucapi import RequestUserInput, SetupAction, UserDataResponse
from ucapi_framework import BaseSetupFlow
from ucapi_framework.discovery import DiscoveredDevice

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.ma_client import (
    MusicPlayMAClient,
    create_long_lived_token,
)

_LOG = logging.getLogger(__name__)


class DeezerSetupFlow(BaseSetupFlow[DeezerConfig]):
    """Music Play setup with discovery first and authentication second."""

    def get_manual_entry_form(self) -> RequestUserInput:
        """Manual server entry. Authentication is always shown afterwards."""
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
                    "id": "preferred_player_name",
                    "label": {
                        "en": "Preferred player",
                        "de": "Bevorzugter Player",
                    },
                    "field": {"text": {"value": "Denon AVC-X4800H"}},
                },
            ],
        )

    async def prepare_input_from_discovery(
        self,
        discovered: DiscoveredDevice,
        additional_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert mDNS discovery result to the manual-entry input format."""
        return {
            "identifier": discovered.identifier,
            "server_url": discovered.address,
            "address": discovered.address,
            "name": additional_input.get("name") or "Music Play",
            "device_name": discovered.name,
            "preferred_player_name": additional_input.get(
                "preferred_player_name",
                "Denon AVC-X4800H",
            ),
        }

    @staticmethod
    def _authentication_form(server_url: str) -> RequestUserInput:
        return RequestUserInput(
            {
                "en": "Music Assistant Login",
                "de": "Music Assistant Anmeldung",
            },
            [
                {
                    "id": "server_info",
                    "label": {
                        "en": "Selected server",
                        "de": "Ausgewählter Server",
                    },
                    "field": {
                        "label": {
                            "value": {
                                "en": server_url,
                                "de": server_url,
                            }
                        }
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
                        "en": "Username (alternative to token)",
                        "de": "Benutzername (Alternative zum Token)",
                    },
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "password",
                    "label": {
                        "en": "Password (alternative to token)",
                        "de": "Passwort (Alternative zum Token)",
                    },
                    # Keep generic text input for Remote firmware compatibility.
                    # It is used only for this transaction and never persisted.
                    "field": {"text": {"value": ""}},
                },
            ],
        )

    async def query_device(
        self,
        input_values: dict[str, Any],
    ) -> DeezerConfig | RequestUserInput:
        """Create the pending config, then ask for authentication."""
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

        preferred = str(
            input_values.get("preferred_player_name", "")
        ).strip() or "Denon AVC-X4800H"

        parsed = urlparse(server_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "Enter a valid Music Assistant URL, "
                "e.g. http://192.168.178.20:8095"
            )

        digest = hashlib.sha1(
            server_url.encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()[:10]

        # BaseSetupFlow supports multi-screen configuration by keeping a
        # pending config. The credentials are intentionally NOT part of it.
        self._pending_device_config = DeezerConfig(
            identifier=f"music_{digest}",
            name=name,
            server_url=server_url,
            access_token="",
            preferred_player_name=preferred,
            poll_interval=10,
        )

        _LOG.info(
            "Music Assistant server selected: %s; requesting authentication",
            server_url,
        )
        return self._authentication_form(server_url)

    async def handle_additional_configuration_response(
        self,
        msg: UserDataResponse,
    ) -> SetupAction | None:
        """Authenticate and populate only the resulting token in pending config."""
        pending = self._pending_device_config
        if pending is None:
            raise ValueError("Music Play setup lost the pending server configuration.")

        access_token = str(
            msg.input_values.get("access_token", "")
        ).strip()
        username = str(msg.input_values.get("username", "")).strip()
        password = str(msg.input_values.get("password", "")).strip()

        if not access_token:
            if not username or not password:
                raise ValueError(
                    "Enter either a Long-Lived Access Token or "
                    "Music Assistant username and password."
                )

            _LOG.info(
                "Authenticating with Music Assistant user account to create "
                "a dedicated Music Play token"
            )
            try:
                access_token = await create_long_lived_token(
                    pending.server_url,
                    username,
                    password,
                )
            except Exception as err:
                _LOG.exception(
                    "Music Assistant username/password authentication failed"
                )
                raise ValueError(
                    "Music Assistant login failed. "
                    "Check username and password."
                ) from err

        # Validate the resulting token before allowing BaseSetupFlow to save it.
        client = MusicPlayMAClient(
            pending.server_url,
            access_token,
        )
        try:
            await client.start()
        except Exception as err:
            _LOG.exception("Music Assistant token validation failed")
            raise ValueError(
                "Could not connect to Music Assistant with these credentials."
            ) from err
        finally:
            await client.close()

        pending.access_token = access_token

        # Username and password never enter DeezerConfig and are discarded here.
        _LOG.info(
            "Music Assistant authentication successful for %s",
            pending.server_url,
        )

        # None tells BaseSetupFlow to persist _pending_device_config and finish.
        return None
