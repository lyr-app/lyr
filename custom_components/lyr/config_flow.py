"""Config flow for Lyr: a host and port, or a Core found over Bonjour."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # Home Assistant 2025.1+
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - older cores
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .api import LyrApiError, LyrClient, LyrConnectionError
from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_TOKEN, default=""): str,
    }
)


class CannotConnect(Exception):
    """The Core did not answer."""


class CoreTooOld(Exception):
    """The Core answers but has no `/api/zones/now-playing`."""


async def _probe(client: LyrClient) -> tuple[str, str]:
    """(coreId, name) — and proof the zone route exists."""
    try:
        identity = await client.identity()
        status = await client.status()
    except LyrConnectionError as err:
        raise CannotConnect from err
    except LyrApiError as err:
        raise CannotConnect from err
    core_id = str((identity or {}).get("coreId") or "").strip()
    if not core_id:
        raise CannotConnect
    try:
        await client.zones()
    except LyrApiError as err:
        if err.status == 404:
            raise CoreTooOld from err
        raise CannotConnect from err
    except LyrConnectionError as err:
        raise CannotConnect from err
    name = str((status or {}).get("friendlyName") or "Lyr").strip() or "Lyr"
    return core_id, name


class LyrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lyr."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._name: str = "Lyr"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            token = (user_input.get(CONF_TOKEN) or "").strip()
            client = LyrClient(async_get_clientsession(self.hass), host, port, token or None)
            try:
                core_id, name = await _probe(client)
            except CoreTooOld:
                errors["base"] = "core_too_old"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error probing the Lyr Core")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(core_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port}
                )
                return self.async_create_entry(
                    title=name,
                    data={CONF_HOST: host, CONF_PORT: port, CONF_TOKEN: token},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A Core advertising `_lyrcore._tcp` (desktop Cores; see README)."""
        host = str(discovery_info.host)
        props = discovery_info.properties or {}
        try:
            port = int(props.get("apiPort") or discovery_info.port or DEFAULT_PORT)
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        client = LyrClient(async_get_clientsession(self.hass), host, port)
        try:
            core_id, name = await _probe(client)
        except CoreTooOld:
            return self.async_abort(reason="core_too_old")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(core_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        self._host, self._port, self._name = host, port, name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={CONF_HOST: self._host, CONF_PORT: self._port, CONF_TOKEN: ""},
            )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._name, "host": f"{self._host}:{self._port}"},
        )
