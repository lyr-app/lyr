"""The Lyr integration: Lyr zones as Home Assistant media players."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LyrClient, LyrError
from .const import CONF_TOKEN, DOMAIN
from .coordinator import LyrConfigEntry, LyrCoordinator

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: LyrConfigEntry) -> bool:
    """Set up Lyr from a config entry."""
    client = LyrClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data.get(CONF_TOKEN) or None,
    )
    try:
        status = await client.status()
    except LyrError as err:
        raise ConfigEntryNotReady(f"Lyr Core not reachable: {err}") from err

    coordinator = LyrCoordinator(
        hass,
        entry,
        client,
        str((status or {}).get("friendlyName") or entry.title or "Lyr"),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # The Core is the hub every zone device hangs off (`via_device`).
    core_id = entry.unique_id or entry.entry_id
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, core_id)},
        manufacturer="Lyr",
        model="Lyr Core",
        name=coordinator.core_name,
        configuration_url=client.base_url,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LyrConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
