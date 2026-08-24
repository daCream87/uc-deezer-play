from __future__ import annotations

import logging
from typing import Any

from ucapi import StatusCodes
from ucapi.remote import Attributes, Features, Remote, States
from ucapi.ui import Buttons
from ucapi_framework import RemoteEntity

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.device import DeezerDevice

_LOG = logging.getLogger(__name__)

COMMANDS = ["POWER_TOGGLE", "PLAY_PAUSE", "STOP", "PREVIOUS", "NEXT", "VOLUME_UP", "VOLUME_DOWN", "MUTE"]


class DeezerRemote(RemoteEntity):
    def __init__(self, device_config: DeezerConfig, device: DeezerDevice):
        self._device = device
        super().__init__(
            f"remote.{device_config.identifier}",
            f"{device_config.name} Tasten",
            features=[Features.SEND_CMD],
            attributes={Attributes.STATE: States.UNKNOWN},
            simple_commands=COMMANDS,
            button_mapping=self._button_mapping(),
            ui_pages=self._ui_pages(),
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self):
        self.update({Attributes.STATE: States.ON if self._device.state.online else States.OFF})

    @staticmethod
    def _send(command): return {"cmd_id": "send_cmd", "params": {"command": command}}

    def _button_mapping(self):
        pairs = [
            (("POWER", "POWER_TOGGLE"), "POWER_TOGGLE"),
            (("PLAY",), "PLAY_PAUSE"),
            (("STOP",), "STOP"),
            (("PREV", "PREVIOUS"), "PREVIOUS"),
            (("NEXT",), "NEXT"),
            (("VOLUME_UP",), "VOLUME_UP"),
            (("VOLUME_DOWN",), "VOLUME_DOWN"),
            (("MUTE",), "MUTE"),
        ]
        result = []
        for button_names, command in pairs:
            button = next(
                (getattr(Buttons, name, None) for name in button_names if getattr(Buttons, name, None) is not None),
                None,
            )
            if button is not None:
                result.append(
                    {
                        "button": button.value,
                        "short_press": self._send(command),
                        "long_press": None,
                    }
                )
        return result

    @staticmethod
    def _text(text, x, y, command, width=1):
        item = {"type": "text", "location": {"x": x, "y": y}, "text": text, "command": {"cmd_id": command}}
        if width != 1: item["size"] = {"width": width, "height": 1}
        return item

    def _ui_pages(self):
        return [{
            "page_id": "deezer",
            "name": "Deezer Play",
            "grid": {"width": 4, "height": 4},
            "items": [
                self._text("DEEZER PLAY", 0, 0, "PLAY_PAUSE", 4),
                self._text("PREV", 0, 1, "PREVIOUS"), self._text("PLAY/PAUSE", 1, 1, "PLAY_PAUSE", 2), self._text("NEXT", 3, 1, "NEXT"),
                self._text("VOL −", 0, 2, "VOLUME_DOWN"), self._text("MUTE", 1, 2, "MUTE", 2), self._text("VOL +", 3, 2, "VOLUME_UP"),
                self._text("STOP", 1, 3, "STOP", 2),
            ],
        }]

    async def _handle_command(self, entity: Remote, cmd_id: str, params: dict[str, Any] | None = None):
        if cmd_id == "send_cmd" and params:
            cmd_id = str(params.get("command", ""))
        mapping = {
            "POWER_TOGGLE": "stop_and_power_off",
            "PLAY_PAUSE": "play_pause",
            "STOP": "stop",
            "PREVIOUS": "previous",
            "NEXT": "next",
            "VOLUME_UP": "volume_up",
            "VOLUME_DOWN": "volume_down",
            "MUTE": "mute_toggle",
        }
        command = mapping.get(cmd_id)
        if not command: return StatusCodes.NOT_IMPLEMENTED
        try:
            return StatusCodes.OK if await self._device.send(command) else StatusCodes.BAD_REQUEST
        except Exception:
            _LOG.exception("Remote command failed: %s", cmd_id)
            return StatusCodes.SERVER_ERROR
