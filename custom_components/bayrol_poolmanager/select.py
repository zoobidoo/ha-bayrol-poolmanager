"""Selects: pump mode, mode and days of each timer interval."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BayrolConfigEntry
from .const import (
    DAY_PRESETS,
    DAY_PRESETS_REV,
    INTERVAL_MODES,
    INTERVAL_MODES_REV,
    ITEM_PUMP_MODE,
    PUMP_MODES,
    PUMP_MODES_REV,
    TIMER_INTERVALS,
)
from .coordinator import parse_int
from .entity import BayrolEntity, BayrolIntervalEntity


async def async_setup_entry(hass: HomeAssistant, entry: BayrolConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    entities: list[SelectEntity] = [PumpModeSelect(c)]
    for n in TIMER_INTERVALS:
        entities += [IntervalModeSelect(c, "interval_mode", n), IntervalDaysSelect(c, "interval_days", n)]
    async_add_entities(entities)


class PumpModeSelect(BayrolEntity, SelectEntity):
    """Auto (timer) / forced on / off."""

    _attr_options = list(PUMP_MODES)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "pump_mode")

    @property
    def current_option(self) -> str | None:
        return PUMP_MODES_REV.get(parse_int(self.coordinator.data.get(ITEM_PUMP_MODE)))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write({ITEM_PUMP_MODE: str(PUMP_MODES[option])})


class IntervalModeSelect(BayrolIntervalEntity, SelectEntity):
    _attr_options = list(INTERVAL_MODES)
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        return INTERVAL_MODES_REV.get(self.interval.mode)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write({TIMER_INTERVALS[self.number]["mode"]: str(INTERVAL_MODES[option])})


class IntervalDaysSelect(BayrolIntervalEntity, SelectEntity):
    """Active days (presets; arbitrary days through the set_timer_interval action)."""

    _attr_options = [*DAY_PRESETS, "custom"]
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        days = self.interval.days
        if days is None:
            return None
        return DAY_PRESETS_REV.get(days, "custom")

    async def async_select_option(self, option: str) -> None:
        if option == "custom":
            return
        await self.coordinator.async_write({TIMER_INTERVALS[self.number]["days"]: str(DAY_PRESETS[option])})
