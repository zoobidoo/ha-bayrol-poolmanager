"""Data update coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BayrolAuthError, BayrolClient, BayrolError, BayrolWriteRefused
from .const import (
    ALL_ITEMS,
    DOMAIN,
    INTERVAL_MODES,
    TIMER_INTERVALS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class TimerInterval:
    """One interval of the filter pump timer."""

    number: int
    mode: int | None
    days: int | None
    start: time | None
    end: time | None
    label: str | None

    @property
    def enabled(self) -> bool:
        return bool(self.days) and self.mode not in (None, INTERVAL_MODES["off"])

    def runs_on(self, weekday: int) -> bool:
        return self.enabled and bool(self.days & (1 << weekday))

    @property
    def duration_hours(self) -> float:
        if self.start is None or self.end is None:
            return 0.0
        s = self.start.hour * 60 + self.start.minute
        e = self.end.hour * 60 + self.end.minute
        minutes = (e - s) % (24 * 60)
        return round(minutes / 60, 2)


@dataclass
class PoolData:
    raw: dict[str, Any]
    intervals: dict[int, TimerInterval] = field(default_factory=dict)

    def get(self, item: str) -> Any:
        return self.raw.get(item)

    def daily_filtration_hours(self, weekday: int | None = None) -> float:
        if weekday is None:
            weekday = dt_util.now().weekday()
        return round(sum(iv.duration_hours for iv in self.intervals.values() if iv.runs_on(weekday)), 2)


def parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        parts = [int(p) for p in str(value).strip().split(":")]
        while len(parts) < 3:
            parts.append(0)
        return time(parts[0] % 24, parts[1], parts[2])
    except (ValueError, IndexError):
        return None


def parse_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class BayrolCoordinator(DataUpdateCoordinator[PoolData]):
    """Polls the PoolManager at a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: BayrolClient,
        scan_interval: int,
        write_client: BayrolClient | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=scan_interval))
        self.client = client
        # Locally the device refuses writes unless a remote user is logged in:
        # an optional cloud client can be used for writes instead.
        self.write_client = write_client or client

    async def _async_update_data(self) -> PoolData:
        try:
            raw = await self.client.async_get(ALL_ITEMS)
        except BayrolAuthError as err:
            raise UpdateFailed(f"Portal authentication failed: {err}") from err
        except BayrolError as err:
            raise UpdateFailed(f"PoolManager unreachable: {err}") from err
        return build_pool_data(raw)

    async def async_write(self, values: dict[str, str]) -> None:
        try:
            await self.write_client.async_set(values)
        except BayrolAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="portal_auth_failed", translation_placeholders={"error": str(err)}
            ) from err
        except BayrolWriteRefused as err:
            key = "write_refused" if self.write_client.is_cloud else "write_refused_local"
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=key, translation_placeholders={"error": str(err)}
            ) from err
        except BayrolError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_failed", translation_placeholders={"error": str(err)}
            ) from err
        if self.data is not None:
            raw = dict(self.data.raw)
            raw.update(values)
            self.async_set_updated_data(build_pool_data(raw))
        await self.async_request_refresh()


def build_pool_data(raw: dict[str, Any]) -> PoolData:
    intervals = {
        n: TimerInterval(
            number=n,
            mode=parse_int(raw.get(ids["mode"])),
            days=parse_int(raw.get(ids["days"])),
            start=parse_time(raw.get(ids["on"])),
            end=parse_time(raw.get(ids["off"])),
            label=raw.get(ids["label"]),
        )
        for n, ids in TIMER_INTERVALS.items()
    }
    return PoolData(raw=raw, intervals=intervals)
