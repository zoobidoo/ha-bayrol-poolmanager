"""Diagnostics: lets users of other PoolManager models report what their device returns."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import BayrolConfigEntry
from .const import CONF_ACCESS_CODE, CONF_DEVICE_ID, CONF_REMOTE_PASSWORD, CONF_REMOTE_USER, WEEKDAYS

TO_REDACT = {
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_ID,
    CONF_ACCESS_CODE,
    CONF_REMOTE_USER,
    CONF_REMOTE_PASSWORD,
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: BayrolConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry (credentials and identifiers redacted)."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "connection": {
            "cloud_reads": coordinator.client.is_cloud,
            "cloud_writes": coordinator.write_client.is_cloud,
            "remote_user_logged_in": coordinator.write_client.remote_logged_in,
        },
        "raw_values": dict(data.raw) if data else None,
        "intervals": {
            n: {
                "enabled": iv.enabled,
                "mode": iv.mode,
                "days": [d for i, d in enumerate(WEEKDAYS) if iv.days and iv.days & (1 << i)],
                "start": iv.start.isoformat() if iv.start else None,
                "end": iv.end.isoformat() if iv.end else None,
            }
            for n, iv in (data.intervals.items() if data else [])
        },
        "last_update_success": coordinator.last_update_success,
    }
