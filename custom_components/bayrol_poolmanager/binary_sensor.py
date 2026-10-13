"""Binary sensors: pump running, alarms."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BayrolConfigEntry
from .const import ITEM_ALARM_COLLECTIVE, ITEM_ALARM_NO_FLOW, ITEM_PUMP_STATUS
from .coordinator import parse_int
from .entity import BayrolEntity


async def async_setup_entry(hass: HomeAssistant, entry: BayrolConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            BayrolBinary(c, "pump_running", ITEM_PUMP_STATUS, BinarySensorDeviceClass.RUNNING, lambda v: v == 0),
            BayrolBinary(c, "alarm", ITEM_ALARM_COLLECTIVE, BinarySensorDeviceClass.PROBLEM, lambda v: v == 1),
            BayrolBinary(c, "no_flow", ITEM_ALARM_NO_FLOW, BinarySensorDeviceClass.PROBLEM, lambda v: v == 1),
        ]
    )


class BayrolBinary(BayrolEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, item, device_class, fn) -> None:
        super().__init__(coordinator, key)
        self._item = item
        self._fn = fn
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        v = parse_int(self.coordinator.data.get(self._item))
        return None if v is None else self._fn(v)
