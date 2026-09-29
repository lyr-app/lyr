"""Polls the Lyr Core for every zone in one call."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LyrApiError, LyrClient, LyrConnectionError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class LyrData:
    """One snapshot of the Core."""

    zones: dict[str, dict[str, Any]] = field(default_factory=dict)
    explicit_filter: dict[str, bool] = field(default_factory=dict)
    lms: dict[str, Any] = field(default_factory=dict)


type LyrConfigEntry = ConfigEntry[LyrCoordinator]


class LyrCoordinator(DataUpdateCoordinator[LyrData]):
    """Fetches `/api/zones/now-playing`."""

    config_entry: LyrConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: LyrConfigEntry,
        client: LyrClient,
        core_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.core_name = core_name

    async def _async_update_data(self) -> LyrData:
        try:
            data = await self.client.zones()
        except LyrConnectionError as err:
            raise UpdateFailed(f"Lyr Core unreachable: {err}") from err
        except LyrApiError as err:
            raise UpdateFailed(f"Lyr Core error: {err}") from err
        zones = {
            str(z.get("id")): z
            for z in (data or {}).get("zones") or []
            if isinstance(z, dict) and z.get("id")
        }
        return LyrData(
            zones=zones,
            explicit_filter=dict((data or {}).get("explicitFilter") or {}),
            lms=dict((data or {}).get("lms") or {}),
        )
