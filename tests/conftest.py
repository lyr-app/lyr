"""Fixtures for the Lyr integration tests.

The payloads are the Lyr Core's real response shapes, with example values.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT

from pytest_homeassistant_custom_component.common import MockConfigEntry

HOST = "192.168.1.20"
PORT = 3000
BASE = f"http://{HOST}:{PORT}"
CORE_ID = "lyrcore_9b45361fd2e46c85eaeb459c4e3a9348"

LIVING_ROOM = "02:00:00:00:00:01"
WIIM = "02:00:00:00:00:02"
RPI = "02:00:00:00:00:03"

STATUS = {
    "friendlyName": "Buttercup mac mini M2",
    "lmsHost": "192.168.1.19",
    "lmsPort": "9000",
}
IDENTITY = {"coreId": CORE_ID, "publicKey": "x", "alg": "ed25519"}

ZONES: dict[str, Any] = {
    "ok": True,
    "at": 1790700000000,
    "lms": {"host": "192.168.1.19", "port": 9000},
    "explicitFilter": {"featureEnabled": True, "active": False},
    "zones": [
        {
            "id": LIVING_ROOM,
            "name": "Living Room",
            "lmsName": "squeezelite-lounge",
            "model": "varese",
            "icon": "varese",
            "hidden": False,
            "connected": True,
            "power": True,
            "state": "paused",
            "volume": 58,
            "muted": False,
            "volumeLimit": 100,
            "shuffle": "off",
            "repeat": "all",
            "position": 61.5,
            "positionAt": 1790700000000,
            "queueIndex": 3,
            "queueLength": 12,
            "syncGroup": [],
            "track": {
                "title": "Says",
                "artist": "Nils Frahm",
                "album": "Spaces",
                "artworkUrl": "http://192.168.1.19:9000/music/4f0ef004/cover.jpg",
                "duration": 301.2,
                "isRadio": False,
                "stationName": "",
            },
        },
        {
            "id": WIIM,
            "name": "WiiM Pro",
            "lmsName": "WiiM Pro",
            "model": "wiim-pro",
            "icon": None,
            "hidden": False,
            "connected": True,
            "power": True,
            "state": "idle",
            "volume": 20,
            "muted": False,
            "volumeLimit": 65,
            "shuffle": "off",
            "repeat": "off",
            "position": None,
            "positionAt": 1790700000000,
            "queueIndex": None,
            "queueLength": 0,
            "syncGroup": [],
            "track": None,
        },
        {
            "id": RPI,
            "name": "39 HiFiBerry",
            "lmsName": "RPi4",
            "model": "dutchdutch-8c",
            "icon": "dutchdutch-8c",
            "hidden": True,
            "connected": True,
            "power": True,
            "state": "idle",
            "volume": 40,
            "muted": False,
            "volumeLimit": 100,
            "shuffle": "off",
            "repeat": "off",
            "position": None,
            "positionAt": 1790700000000,
            "queueIndex": None,
            "queueLength": 0,
            "syncGroup": [],
            "track": None,
        },
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/lyr.

    The `hass` fixture puts the plugin's own testing_config first on sys.path,
    so `custom_components` resolves there; add this folder to its search path.
    """
    import custom_components

    here = str(Path(__file__).resolve().parents[1] / "custom_components")
    if here not in custom_components.__path__:
        custom_components.__path__.append(here)


@pytest.fixture
def zones_payload() -> dict[str, Any]:
    return copy.deepcopy(ZONES)


@pytest.fixture
def core(aioclient_mock, zones_payload):
    """A Core answering the read routes."""
    aioclient_mock.get(f"{BASE}/api/status", json=STATUS)
    aioclient_mock.get(f"{BASE}/api/core/identity", json=IDENTITY)
    aioclient_mock.get(f"{BASE}/api/zones/now-playing", json=zones_payload)
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain="lyr",
        title="Buttercup mac mini M2",
        unique_id=CORE_ID,
        data={CONF_HOST: HOST, CONF_PORT: PORT, "token": ""},
    )
