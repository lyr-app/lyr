"""Lyr zones as media players.

One entity per Lyr Server (LMS) player the Core reports. Names, the hidden
flag, the volume ceiling and the now-playing metadata are Lyr's, not LMS's —
that difference is the reason this integration exists next to Home Assistant's
own Squeezebox integration (see the README).
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_ENQUEUE,
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
    SearchMedia,
    SearchMediaQuery,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import LyrApiError, LyrConnectionError
from .browse_media import ROOT_ID, async_browse, is_lyr_id, parse_id, root_node, search_results
from .const import (
    ATTR_ARTIST,
    ATTR_KIND,
    ATTR_PROMPT,
    ATTR_QUERY,
    ATTR_SHUFFLE,
    DOMAIN,
    ITEM_KINDS,
    SERVICE_PLAY_PROMPT,
    SERVICE_PLAY_SEARCH,
    SERVICE_START_RADIO,
)
from .coordinator import LyrConfigEntry, LyrCoordinator

_LOGGER = logging.getLogger(__name__)

# One command at a time: Lyr Server answers a burst with ECONNRESET and then
# refuses the sender for a while (PROJECT_NOTES, the stall-sweep section).
PARALLEL_UPDATES = 1

STATE_MAP: dict[str, MediaPlayerState] = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "idle": MediaPlayerState.IDLE,
    "off": MediaPlayerState.OFF,
}
REPEAT_TO_HA: dict[str, RepeatMode] = {
    "off": RepeatMode.OFF,
    "one": RepeatMode.ONE,
    "all": RepeatMode.ALL,
}
REPEAT_FROM_HA: dict[RepeatMode, str] = {v: k for k, v in REPEAT_TO_HA.items()}

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.MEDIA_ENQUEUE
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SEARCH_MEDIA
    | MediaPlayerEntityFeature.GROUPING
)

# Lyr Server's volume moves in whole percent; one press of volume up/down.
VOLUME_STEP_PERCENT = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LyrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a media player for every zone, and for zones that appear later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_zones() -> None:
        new = [
            LyrZoneEntity(coordinator, pid)
            for pid in coordinator.data.zones
            if pid not in known
        ]
        if new:
            known.update(e.player_id for e in new)
            async_add_entities(new)

    _add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_zones))

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PLAY_PROMPT,
        {vol.Required(ATTR_PROMPT): vol.All(cv.string, vol.Length(min=1, max=500))},
        "async_play_prompt",
    )
    platform.async_register_entity_service(
        SERVICE_START_RADIO,
        {vol.Optional(ATTR_ARTIST): cv.string},
        "async_start_radio",
    )
    platform.async_register_entity_service(
        SERVICE_PLAY_SEARCH,
        {
            vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1, max=200)),
            vol.Optional(ATTR_KIND, default="any"): vol.In(("any", *ITEM_KINDS)),
            vol.Optional(ATTR_SHUFFLE, default=False): cv.boolean,
        },
        "async_play_search",
    )


class LyrZoneEntity(CoordinatorEntity[LyrCoordinator], MediaPlayerEntity):
    """A Lyr zone."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = SUPPORTED_FEATURES
    _attr_media_image_remotely_accessible = False

    def __init__(self, coordinator: LyrCoordinator, player_id: str) -> None:
        super().__init__(coordinator)
        self.player_id = player_id
        core_id = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{core_id}_{player_id}"
        zone = self._zone or {}
        # A player hidden in the Lyr app starts disabled here too; the user can
        # still enable it in Home Assistant.
        self._attr_entity_registry_enabled_default = not zone.get("hidden", False)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, player_id)},
            name=str(zone.get("name") or player_id),
            manufacturer="Lyr",
            model=str(zone.get("model") or "Lyr Server player"),
            via_device=(DOMAIN, core_id),
        )

    # -- state -------------------------------------------------------------

    @property
    def _zone(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        return data.zones.get(self.player_id) if data else None

    @property
    def _track(self) -> dict[str, Any]:
        return (self._zone or {}).get("track") or {}

    @property
    def available(self) -> bool:
        zone = self._zone
        return super().available and zone is not None and bool(zone.get("connected"))

    @property
    def state(self) -> MediaPlayerState | None:
        zone = self._zone
        if not zone:
            return None
        return STATE_MAP.get(str(zone.get("state")), MediaPlayerState.IDLE)

    @property
    def volume_level(self) -> float | None:
        vol_ = (self._zone or {}).get("volume")
        return None if vol_ is None else max(0.0, min(1.0, float(vol_) / 100))

    @property
    def is_volume_muted(self) -> bool | None:
        return bool((self._zone or {}).get("muted"))

    @property
    def shuffle(self) -> bool | None:
        return (self._zone or {}).get("shuffle", "off") != "off"

    @property
    def repeat(self) -> RepeatMode | None:
        return REPEAT_TO_HA.get(str((self._zone or {}).get("repeat", "off")), RepeatMode.OFF)

    @property
    def media_title(self) -> str | None:
        return self._track.get("title") or None

    @property
    def media_artist(self) -> str | None:
        return self._track.get("artist") or None

    @property
    def media_album_name(self) -> str | None:
        return self._track.get("album") or None

    @property
    def media_channel(self) -> str | None:
        return self._track.get("stationName") or None

    @property
    def media_image_url(self) -> str | None:
        return self._track.get("artworkUrl") or None

    @property
    def media_duration(self) -> int | None:
        dur = self._track.get("duration")
        return int(dur) if dur else None

    @property
    def media_position(self) -> int | None:
        pos = (self._zone or {}).get("position")
        return None if pos is None else int(pos)

    @property
    def media_position_updated_at(self) -> datetime | None:
        zone = self._zone or {}
        if zone.get("position") is None or not zone.get("positionAt"):
            return None
        return dt_util.utc_from_timestamp(float(zone["positionAt"]) / 1000)

    @property
    def group_members(self) -> list[str] | None:
        ids = (self._zone or {}).get("syncGroup") or []
        if not ids:
            return None
        registry = er.async_get(self.hass)
        core_id = self.coordinator.config_entry.unique_id or self.coordinator.config_entry.entry_id
        members = [
            registry.async_get_entity_id("media_player", DOMAIN, f"{core_id}_{pid}")
            for pid in ids
        ]
        return [m for m in members if m]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone or {}
        return {
            "lyr_player_id": self.player_id,
            "lyr_server_name": zone.get("lmsName"),
            "volume_limit": (zone.get("volumeLimit") or 100) / 100,
            "hidden_in_lyr": bool(zone.get("hidden")),
        }

    # -- commands ----------------------------------------------------------

    async def _command(self, action: str, **args: Any) -> None:
        try:
            await self.coordinator.client.command(self.player_id, action, **args)
        except LyrApiError as err:
            raise HomeAssistantError(f"Lyr refused {action}: {err.message}") from err
        except LyrConnectionError as err:
            raise HomeAssistantError(f"Lyr Core unreachable: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self._command("power", on=True)

    async def async_turn_off(self) -> None:
        await self._command("power", on=False)

    async def async_media_play(self) -> None:
        await self._command("play")

    async def async_media_pause(self) -> None:
        await self._command("pause")

    async def async_media_play_pause(self) -> None:
        await self._command("toggle")

    async def async_media_stop(self) -> None:
        await self._command("stop")

    async def async_media_next_track(self) -> None:
        await self._command("next")

    async def async_media_previous_track(self) -> None:
        await self._command("previous")

    async def async_media_seek(self, position: float) -> None:
        await self._command("seek", position=position)

    async def async_set_volume_level(self, volume: float) -> None:
        # The Core clamps to the zone's ceiling (volume_limit), as the app does.
        await self._command("volume", level=round(volume * 100))

    async def async_volume_up(self) -> None:
        await self._command("volume_step", delta=VOLUME_STEP_PERCENT)

    async def async_volume_down(self) -> None:
        await self._command("volume_step", delta=-VOLUME_STEP_PERCENT)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._command("mute", muted=mute)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._command("shuffle", mode="songs" if shuffle else "off")

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._command("repeat", mode=REPEAT_FROM_HA.get(repeat, "off"))

    def _player_id_for_entity(self, entity_id: str) -> str | None:
        entry = er.async_get(self.hass).async_get(entity_id)
        if not entry or entry.platform != DOMAIN or not entry.unique_id:
            return None
        return entry.unique_id.rsplit("_", 1)[-1]

    async def async_join_players(self, group_members: list[str]) -> None:
        members = []
        for entity_id in group_members:
            pid = self._player_id_for_entity(entity_id)
            if not pid:
                raise ServiceValidationError(
                    f"{entity_id} is not a Lyr zone; Lyr can only group its own zones"
                )
            members.append(pid)
        await self._command("sync", members=members)

    async def async_unjoin_player(self) -> None:
        await self._command("unsync")

    # -- media -------------------------------------------------------------

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        announce: bool | None = None,
        **kwargs: Any,
    ) -> None:
        if announce:
            raise ServiceValidationError(
                "Lyr does not play announcements yet; see the integration README"
            )
        enqueue: MediaPlayerEnqueue | None = kwargs.get(ATTR_MEDIA_ENQUEUE)

        if media_source.is_media_source_id(media_id):
            item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            media_id = async_process_play_media_url(self.hass, item.url)

        if is_lyr_id(media_id):
            parsed = parse_id(media_id)
            if not parsed or parsed[0] not in ITEM_KINDS:
                raise ServiceValidationError(f"Cannot play {media_id}")
            if enqueue in (MediaPlayerEnqueue.ADD, MediaPlayerEnqueue.NEXT):
                raise ServiceValidationError(
                    "Lyr replaces the queue when it plays a library item; "
                    "adding one to the queue is not supported yet"
                )
            kind, item_id = parsed
            try:
                await self.coordinator.client.play_item(self.player_id, kind, item_id)
            except LyrApiError as err:
                raise HomeAssistantError(f"Lyr could not play that: {err.message}") from err
            except LyrConnectionError as err:
                raise HomeAssistantError(f"Lyr Core unreachable: {err}") from err
            await self.coordinator.async_request_refresh()
            return

        if media_id.startswith(("http://", "https://")):
            if enqueue == MediaPlayerEnqueue.ADD:
                await self._command("play_url", url=media_id, enqueue="add")
            elif enqueue == MediaPlayerEnqueue.NEXT:
                await self._command("play_url", url=media_id, enqueue="next")
            elif enqueue == MediaPlayerEnqueue.PLAY:
                await self._command("play_url", url=media_id, enqueue="next")
                await self._command("next")
            else:
                await self._command("play_url", url=media_id, enqueue="replace")
            return

        raise ServiceValidationError(f"Lyr cannot play media id {media_id}")

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        if media_content_id and media_source.is_media_source_id(media_content_id):
            return await media_source.async_browse_media(
                self.hass, media_content_id, content_filter=_audio_only
            )
        if not media_content_id or media_content_id == ROOT_ID:
            extra: list[BrowseMedia] = []
            try:
                sources = await media_source.async_browse_media(
                    self.hass, None, content_filter=_audio_only
                )
                if sources.domain is None:
                    extra.extend(sources.children or [])
                else:
                    extra.append(sources)
            except Exception:  # noqa: BLE001 - media_source is optional here
                _LOGGER.debug("media_source browse failed", exc_info=True)
            return root_node(extra)
        try:
            return await async_browse(self.coordinator.client, media_content_id)
        except LyrConnectionError as err:
            raise HomeAssistantError(f"Lyr Core unreachable: {err}") from err

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        try:
            items = await self.coordinator.client.resolve(query.search_query)
        except LyrConnectionError as err:
            raise HomeAssistantError(f"Lyr Core unreachable: {err}") from err
        return SearchMedia(result=search_results(self.coordinator.client, items))

    # -- Lyr services ------------------------------------------------------

    async def async_play_prompt(self, prompt: str) -> None:
        """Ask Liora for music matching `prompt` and play it here."""
        try:
            await self.coordinator.client.play_prompt(self.player_id, prompt)
        except LyrApiError as err:
            raise HomeAssistantError(f"Liora could not start: {err.message}") from err

    async def async_start_radio(self, artist: str | None = None) -> None:
        """Radio from an artist, or from the artist playing here now."""
        try:
            await self.coordinator.client.play_radio(self.player_id, artist)
        except LyrApiError as err:
            raise HomeAssistantError(f"Lyr radio could not start: {err.message}") from err

    async def async_play_search(self, query: str, kind: str = "any", shuffle: bool = False) -> None:
        """Play the best library match for `query` (what Siri does)."""
        items = await self.coordinator.client.resolve(query, kind)
        if not items:
            raise ServiceValidationError(f"Nothing in the Lyr library matches “{query}”")
        best = items[0]
        try:
            await self.coordinator.client.play_item(
                self.player_id, str(best["kind"]), str(best["id"]), shuffle
            )
        except LyrApiError as err:
            raise HomeAssistantError(f"Lyr could not play {best.get('title')}: {err.message}") from err
        await self.coordinator.async_request_refresh()


def _audio_only(item: BrowseMedia) -> bool:
    return str(item.media_content_type or "").startswith("audio/")
