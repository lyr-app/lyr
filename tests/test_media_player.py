"""Media player, browse and switch tests against a mocked Core."""

from __future__ import annotations

import json

import pytest

from homeassistant.components.media_player import (
    ATTR_GROUP_MEMBERS,
    ATTR_MEDIA_ALBUM_NAME,
    ATTR_MEDIA_ARTIST,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_TITLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MP_DOMAIN,
    SERVICE_JOIN,
    SERVICE_PLAY_MEDIA,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_MEDIA_PAUSE,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_SET,
    STATE_PAUSED,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import BASE, LIVING_ROOM, RPI, WIIM

LIVING = "media_player.living_room"
WIIM_ENTITY = "media_player.wiim_pro"


async def _setup(hass: HomeAssistant, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def _posted(aioclient_mock, path: str) -> list[dict]:
    """Bodies POSTed to `path`, oldest first."""
    out = []
    for method, url, data, _headers in aioclient_mock.mock_calls:
        if method.upper() in ("POST", "PATCH") and str(url).endswith(path):
            out.append(data if isinstance(data, dict) else json.loads(data or "{}"))
    return out


async def test_zones_become_media_players(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    state = hass.states.get(LIVING)
    assert state is not None, "the Lyr rename names the entity, not the LMS name"
    assert state.state == STATE_PAUSED
    assert state.attributes[ATTR_MEDIA_TITLE] == "Says"
    assert state.attributes[ATTR_MEDIA_ARTIST] == "Nils Frahm"
    assert state.attributes[ATTR_MEDIA_ALBUM_NAME] == "Spaces"
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == pytest.approx(0.58)
    assert state.attributes["lyr_server_name"] == "squeezelite-lounge"

    registry = er.async_get(hass)
    hidden = registry.async_get_entity_id("media_player", "lyr", f"{config_entry.unique_id}_{RPI}")
    assert hidden is not None
    assert registry.async_get(hidden).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_volume_goes_through_the_core(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.post(f"{BASE}/api/zones/{WIIM}/command", json={"ok": True, "volume": 65, "limit": 65})
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: WIIM_ENTITY, ATTR_MEDIA_VOLUME_LEVEL: 0.9},
        blocking=True,
    )
    assert _posted(core, f"/api/zones/{WIIM}/command")[-1] == {"action": "volume", "level": 90}
    assert hass.states.get(WIIM_ENTITY).attributes["volume_limit"] == pytest.approx(0.65)


async def test_transport_and_power(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.post(f"{BASE}/api/zones/{LIVING_ROOM}/command", json={"ok": True})
    await hass.services.async_call(MP_DOMAIN, SERVICE_MEDIA_PAUSE, {ATTR_ENTITY_ID: LIVING}, blocking=True)
    await hass.services.async_call(MP_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIVING}, blocking=True)
    bodies = _posted(core, f"/api/zones/{LIVING_ROOM}/command")
    assert bodies[-2:] == [{"action": "pause"}, {"action": "power", "on": True}]


async def test_play_library_album(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.post(f"{BASE}/api/shortcuts/play-item", json={"success": True, "queued": 10})
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: LIVING,
            ATTR_MEDIA_CONTENT_TYPE: "album",
            ATTR_MEDIA_CONTENT_ID: "lyr:album:https://0000000000.airable.io/qobuz/album/zf9gie0tc8b6a",
        },
        blocking=True,
    )
    assert _posted(core, "/api/shortcuts/play-item")[-1] == {
        "playerId": LIVING_ROOM,
        "kind": "album",
        "id": "https://0000000000.airable.io/qobuz/album/zf9gie0tc8b6a",
        "shuffle": False,
    }


async def test_announce_is_refused(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: LIVING,
                ATTR_MEDIA_CONTENT_TYPE: "music",
                ATTR_MEDIA_CONTENT_ID: "http://ha.local/tts.mp3",
                "announce": True,
            },
            blocking=True,
        )


async def test_join_maps_entities_to_players(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.post(f"{BASE}/api/zones/{LIVING_ROOM}/command", json={"ok": True})
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_JOIN,
        {ATTR_ENTITY_ID: LIVING, ATTR_GROUP_MEMBERS: [WIIM_ENTITY]},
        blocking=True,
    )
    assert _posted(core, f"/api/zones/{LIVING_ROOM}/command")[-1] == {
        "action": "sync",
        "members": [WIIM],
    }


async def test_lyr_services(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.post(f"{BASE}/api/zones/{LIVING_ROOM}/play-prompt", status=202, json={"ok": True})
    core.post(f"{BASE}/api/zones/{LIVING_ROOM}/play-radio", status=202, json={"ok": True})
    core.get(
        f"{BASE}/api/shortcuts/resolve",
        json={"success": True, "items": [{"kind": "artist", "id": "Nils Frahm", "title": "Nils Frahm"}]},
    )
    core.post(f"{BASE}/api/shortcuts/play-item", json={"success": True, "queued": 40})

    await hass.services.async_call(
        "lyr", "play_prompt", {ATTR_ENTITY_ID: LIVING, "prompt": "rainy sunday piano"}, blocking=True
    )
    await hass.services.async_call("lyr", "start_radio", {ATTR_ENTITY_ID: LIVING}, blocking=True)
    await hass.services.async_call(
        "lyr", "play_search", {ATTR_ENTITY_ID: LIVING, "query": "nils frahm", "shuffle": True}, blocking=True
    )
    assert _posted(core, f"/api/zones/{LIVING_ROOM}/play-prompt")[-1] == {"prompt": "rainy sunday piano"}
    assert _posted(core, f"/api/zones/{LIVING_ROOM}/play-radio")[-1] == {}
    assert _posted(core, "/api/shortcuts/play-item")[-1] == {
        "playerId": LIVING_ROOM,
        "kind": "artist",
        "id": "Nils Frahm",
        "shuffle": True,
    }


async def test_browse_root_and_album(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.get(
        f"{BASE}/api/library/tracks",
        json={
            "items": [
                {"key": "k2", "title": "B", "artistName": "1,2,3", "albumTitle": "New Heaven", "trackNumber": 2, "artworkUrl": "/music/f8a1fec6/cover.jpg"},
                {"key": "k1", "title": "A", "artistName": "1,2,3", "albumTitle": "New Heaven", "trackNumber": 1, "artworkUrl": "/music/f8a1fec6/cover.jpg"},
            ]
        },
    )
    entity = hass.data["entity_components"][MP_DOMAIN].get_entity(LIVING)
    root = await entity.async_browse_media()
    assert [c.title for c in root.children][:4] == [
        "Playlists",
        "Recently added albums",
        "Artists",
        "Genres",
    ]
    album = await entity.async_browse_media("album", "lyr:album:28714")
    assert album.title == "New Heaven"
    assert [c.title for c in album.children] == ["A — 1,2,3", "B — 1,2,3"]
    assert album.thumbnail.startswith(f"{BASE}/api/image-proxy?url=%2Fmusic%2Ff8a1fec6")


async def test_explicit_filter_switch(hass: HomeAssistant, core, config_entry) -> None:
    await _setup(hass, config_entry)
    core.patch(f"{BASE}/api/user-prefs", json={"success": True})
    switch = "switch.buttercup_mac_mini_m2_skip_explicit_tracks"
    assert hass.states.get(switch).state == "off"
    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True)
    assert _posted(core, "/api/user-prefs")[-1] == {"settings": {"explicitFilterActive": True}}


async def test_explicit_switch_unavailable_while_feature_off(
    hass: HomeAssistant, aioclient_mock, config_entry, zones_payload
) -> None:
    from .conftest import IDENTITY, STATUS

    zones_payload["explicitFilter"] = {"featureEnabled": False, "active": False}
    aioclient_mock.get(f"{BASE}/api/status", json=STATUS)
    aioclient_mock.get(f"{BASE}/api/core/identity", json=IDENTITY)
    aioclient_mock.get(f"{BASE}/api/zones/now-playing", json=zones_payload)
    await _setup(hass, config_entry)
    assert hass.states.get("switch.buttercup_mac_mini_m2_skip_explicit_tracks").state == STATE_UNAVAILABLE
