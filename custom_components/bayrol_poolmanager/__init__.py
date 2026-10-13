"""Unofficial Home Assistant integration for the Bayrol PoolManager 5."""

from __future__ import annotations

from datetime import time

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import BayrolClient
from .const import (
    CONF_ACCESS_CODE,
    CONF_CONNECTION,
    CONF_DEVICE_ID,
    CONF_REMOTE_PASSWORD,
    CONF_REMOTE_USER,
    CONF_SCAN_INTERVAL,
    CONNECTION_LOCAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    INTERVAL_MODES,
    TIMER_INTERVALS,
    WEEKDAYS,
)
from .coordinator import BayrolCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.TIME]

SERVICE_SET_INTERVAL = "set_timer_interval"
SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Required("interval"): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
        vol.Optional("start"): cv.time,
        vol.Optional("end"): cv.time,
        vol.Optional("mode"): vol.In(list(INTERVAL_MODES)),
        vol.Optional("days"): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
    }
)

type BayrolConfigEntry = ConfigEntry[BayrolCoordinator]


def _fmt(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}:00"


def _session(hass: HomeAssistant) -> aiohttp.ClientSession:
    # Dedicated session: the portal relies on cookies, and the local device is
    # addressed by IP (unsafe cookie jar needed).
    return async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True))


async def async_setup_entry(hass: HomeAssistant, entry: BayrolConfigEntry) -> bool:
    """Set up a PoolManager from a config entry."""
    data = entry.data
    opts = entry.options
    local = data.get(CONF_CONNECTION) == CONNECTION_LOCAL
    client = BayrolClient(
        _session(hass),
        host=data.get(CONF_HOST) if local else None,
        username=None if local else data.get(CONF_USERNAME),
        password=None if local else data.get(CONF_PASSWORD),
        device_id=data.get(CONF_DEVICE_ID),
        access_code=data.get(CONF_ACCESS_CODE),
        remote_user=opts.get(CONF_REMOTE_USER),
        remote_password=opts.get(CONF_REMOTE_PASSWORD),
    )
    write_client = None
    if local and not opts.get(CONF_REMOTE_USER) and opts.get(CONF_USERNAME) and opts.get(CONF_PASSWORD):
        # Local reads, writes through the cloud portal.
        write_client = BayrolClient(
            _session(hass),
            username=opts[CONF_USERNAME],
            password=opts[CONF_PASSWORD],
            device_id=opts.get(CONF_DEVICE_ID) or None,
            access_code=data.get(CONF_ACCESS_CODE),
        )
    coordinator = BayrolCoordinator(hass, client, opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL), write_client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    if not hass.services.has_service(DOMAIN, SERVICE_SET_INTERVAL):

        async def _handle_set_interval(call: ServiceCall) -> None:
            entries = [
                e
                for e in hass.config_entries.async_loaded_entries(DOMAIN)
                if not call.data.get("entry_id") or e.entry_id == call.data["entry_id"]
            ]
            if not entries:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_device")
            coord: BayrolCoordinator = entries[0].runtime_data
            ids = TIMER_INTERVALS[call.data["interval"]]
            values: dict[str, str] = {}
            if "start" in call.data:
                values[ids["on"]] = _fmt(call.data["start"])
            if "end" in call.data:
                values[ids["off"]] = _fmt(call.data["end"])
            if "mode" in call.data:
                values[ids["mode"]] = str(INTERVAL_MODES[call.data["mode"]])
            if "days" in call.data:
                mask = sum(1 << WEEKDAYS.index(d) for d in set(call.data["days"]))
                values[ids["days"]] = str(mask)
            if not values:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_change")
            await coord.async_write(values)

        hass.services.async_register(DOMAIN, SERVICE_SET_INTERVAL, _handle_set_interval, schema=SERVICE_SCHEMA)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BayrolConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not [e for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        hass.services.async_remove(DOMAIN, SERVICE_SET_INTERVAL)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: BayrolConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
