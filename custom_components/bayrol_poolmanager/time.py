"""Start and end time of each filter pump timer interval."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BayrolConfigEntry
from .const import TIMER_INTERVALS
from .coordinator import BayrolCoordinator
from .entity import BayrolIntervalEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BayrolConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [IntervalTime(c, "interval_start", n, "on") for n in TIMER_INTERVALS]
        + [IntervalTime(c, "interval_end", n, "off") for n in TIMER_INTERVALS]
    )


class IntervalTime(BayrolIntervalEntity, TimeEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BayrolCoordinator, key: str, number: int, field: str) -> None:
        super().__init__(coordinator, key, number)
        self._field = field

    @property
    def native_value(self) -> time | None:
        return self.interval.start if self._field == "on" else self.interval.end

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_write(
            {TIMER_INTERVALS[self.number][self._field]: f"{value.hour:02d}:{value.minute:02d}:00"}
        )
