"""Config flow tests."""

from __future__ import annotations

from ipaddress import ip_address

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import BASE, CORE_ID, HOST, IDENTITY, PORT, STATUS


async def test_user_flow_creates_entry(hass: HomeAssistant, core) -> None:
    result = await hass.config_entries.flow.async_init("lyr", context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: PORT, "token": ""}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Buttercup mac mini M2"
    assert result["result"].unique_id == CORE_ID
    assert result["data"] == {CONF_HOST: HOST, CONF_PORT: PORT, "token": ""}


async def test_user_flow_core_without_zone_route(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/status", json=STATUS)
    aioclient_mock.get(f"{BASE}/api/core/identity", json=IDENTITY)
    aioclient_mock.get(f"{BASE}/api/zones/now-playing", status=404, json={"error": "not found"})
    result = await hass.config_entries.flow.async_init("lyr", context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: PORT, "token": ""}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "core_too_old"}


async def test_user_flow_unreachable(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/core/identity", exc=TimeoutError())
    result = await hass.config_entries.flow.async_init("lyr", context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PORT: PORT, "token": ""}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_zeroconf_flow(hass: HomeAssistant, core) -> None:
    info = ZeroconfServiceInfo(
        ip_address=ip_address(HOST),
        ip_addresses=[ip_address(HOST)],
        hostname="lyr-core.local.",
        name="Buttercup._lyrcore._tcp.local.",
        port=PORT,
        type="_lyrcore._tcp.local.",
        properties={"id": "abcd1234", "apiPort": str(PORT), "proto": "http"},
    )
    result = await hass.config_entries.flow.async_init(
        "lyr", context={"source": SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == CORE_ID
