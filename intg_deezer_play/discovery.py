from __future__ import annotations

import logging
from typing import Any

from ucapi_framework import DiscoveredDevice
from ucapi_framework.discovery import MDNSDiscovery
from zeroconf import IPVersion

_LOG = logging.getLogger(__name__)

MUSIC_ASSISTANT_MDNS_TYPE = "_mass._tcp.local."


class MusicAssistantDiscovery(MDNSDiscovery):
    """Discover Music Assistant servers advertised over mDNS."""

    def __init__(self, timeout: int = 4) -> None:
        super().__init__(service_type=MUSIC_ASSISTANT_MDNS_TYPE, timeout=timeout)

    def parse_mdns_service(self, service_info: Any) -> DiscoveredDevice | None:
        addresses = service_info.parsed_addresses(IPVersion.V4Only)
        ip = next(
            (
                address
                for address in addresses
                if not address.startswith(("127.", "169.254."))
            ),
            None,
        )
        if not ip:
            return None

        properties: dict[str, str] = {}
        for raw_key, raw_value in (service_info.properties or {}).items():
            try:
                key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
                value = raw_value.decode() if isinstance(raw_value, bytes) else str(raw_value)
                properties[key] = value
            except Exception:
                continue

        port = int(service_info.port or 8095)
        use_ssl = properties.get("use_ssl", "").lower() == "true"
        scheme = "https" if use_ssl else "http"
        address = f"{scheme}://{ip}:{port}"

        server_id = (
            properties.get("server_id")
            or properties.get("id")
            or service_info.name.split(".", 1)[0]
        )
        identifier = str(server_id).replace("-", "_")

        base_url = properties.get("base_url", "")
        friendly_host = ""
        if "://" in base_url:
            friendly_host = base_url.split("://", 1)[1].split(":", 1)[0]
        name = (
            f"Music Assistant ({friendly_host})"
            if friendly_host
            else f"Music Assistant ({ip})"
        )

        _LOG.info("Discovered %s at %s", name, address)
        return DiscoveredDevice(
            identifier=identifier,
            name=name,
            address=address,
            extra_data={"port": port},
        )
