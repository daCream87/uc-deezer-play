from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from ucapi import DeviceStates
from ucapi_framework import BaseConfigManager, get_config_path

from intg_deezer_play.config import DeezerConfig
from intg_deezer_play.driver import DeezerDriver
from intg_deezer_play.setup_flow import DeezerSetupFlow

__version__ = "0.2.2"
_LOG = logging.getLogger(__name__)


def _manifest_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "driver.json"
    return Path(__file__).resolve().parent.parent / "driver.json"


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)-24s | %(message)s")
    _LOG.info("Starting Music Play integration v%s", __version__)

    manifest = _manifest_path()
    if not manifest.is_file():
        raise FileNotFoundError(f"Remote 3 manifest not found: {manifest}")

    driver = DeezerDriver()
    config_path = get_config_path(driver.api.config_dir_path or "")
    config_manager = BaseConfigManager(
        config_path,
        add_handler=driver.on_device_added,
        remove_handler=driver.on_device_removed,
        config_class=DeezerConfig,
    )
    driver.config_manager = config_manager

    setup_handler = DeezerSetupFlow.create_handler(driver)
    await driver.api.init(str(manifest), setup_handler)
    await driver.register_all_device_instances(connect=False)

    await driver.api.set_device_state(
        DeviceStates.CONNECTED if len(list(config_manager.all())) else DeviceStates.DISCONNECTED
    )
    await asyncio.Future()
