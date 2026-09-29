"""The explicit filter as a switch.

The filter is household-wide and enforced on the Core at the stream (PROJECT_NOTES
"Explicit filter"), so it works with no Lyr app open — which is what makes it
useful from an automation ("kids' bedtime: filter on"). It only acts while the
feature itself is enabled in Lyr's Settings; while it is not, the switch is
unavailable rather than pretending.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import LyrError
from .const import DOMAIN
from .coordinator import LyrConfigEntry, LyrCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LyrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LyrExplicitFilterSwitch(entry.runtime_data)])


class LyrExplicitFilterSwitch(CoordinatorEntity[LyrCoordinator], SwitchEntity):
    """Skip explicit tracks on every zone."""

    _attr_has_entity_name = True
    _attr_translation_key = "explicit_filter"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LyrCoordinator) -> None:
        super().__init__(coordinator)
        core_id = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{core_id}_explicit_filter"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, core_id)})

    @property
    def _state(self) -> dict[str, bool]:
        return self.coordinator.data.explicit_filter if self.coordinator.data else {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._state.get("featureEnabled"))

    @property
    def is_on(self) -> bool:
        return bool(self._state.get("active"))

    async def _set(self, active: bool) -> None:
        try:
            await self.coordinator.client.set_explicit_filter(active)
        except LyrError as err:
            raise HomeAssistantError(f"Lyr could not change the explicit filter: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
