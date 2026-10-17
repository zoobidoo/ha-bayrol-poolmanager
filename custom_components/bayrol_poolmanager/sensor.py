"""Sensors: measurements, pump status, scheduled filtration time."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BayrolConfigEntry
from .const import (
    INTERVAL_MODES_REV,
    ITEM_DOSING_CL,
    ITEM_DOSING_PH,
    ITEM_PH,
    ITEM_PH_SETPOINT,
    ITEM_PUMP_STATUS,
    ITEM_REDOX,
    ITEM_REDOX_SETPOINT,
    ITEM_TEMP,
    PUMP_STATUS,
    WEEKDAYS,
)
from .coordinator import PoolData, parse_int
from .entity import BayrolEntity, BayrolIntervalEntity


def _float(item: str) -> Callable[[PoolData], Any]:
    def _get(data: PoolData) -> float | None:
        try:
            return float(str(data.get(item)).strip())
        except (TypeError, ValueError):
            return None

    return _get


def _text(item: str) -> Callable[[PoolData], Any]:
    def _get(data: PoolData) -> str | None:
        v = data.get(item)
        return str(v).strip() if v not in (None, "") else None

    return _get


def _pump_status(data: PoolData) -> str | None:
    return PUMP_STATUS.get(parse_int(data.get(ITEM_PUMP_STATUS)))


@dataclass(frozen=True, kw_only=True)
class BayrolSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PoolData], Any]


SENSORS: tuple[BayrolSensorDescription, ...] = (
    BayrolSensorDescription(
        key="ph",
        value_fn=_float(ITEM_PH),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PH,
        suggested_display_precision=2,
    ),
    BayrolSensorDescription(
        key="redox",
        value_fn=_float(ITEM_REDOX),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        suggested_display_precision=0,
    ),
    BayrolSensorDescription(
        key="water_temperature",
        value_fn=_float(ITEM_TEMP),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    BayrolSensorDescription(
        key="ph_setpoint",
        value_fn=_float(ITEM_PH_SETPOINT),
        entity_registry_enabled_default=True,
        suggested_display_precision=2,
    ),
    BayrolSensorDescription(
        key="redox_setpoint",
        value_fn=_float(ITEM_REDOX_SETPOINT),
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        suggested_display_precision=0,
    ),
    BayrolSensorDescription(
        key="pump_status",
        value_fn=_pump_status,
        device_class=SensorDeviceClass.ENUM,
        options=list(PUMP_STATUS.values()),
    ),
    BayrolSensorDescription(key="dosing_ph_status", value_fn=_text(ITEM_DOSING_PH)),
    BayrolSensorDescription(key="dosing_chlorine_status", value_fn=_text(ITEM_DOSING_CL)),
    BayrolSensorDescription(
        key="daily_filtration",
        value_fn=lambda d: d.daily_filtration_hours(),
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: BayrolConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [BayrolSensor(coordinator, d) for d in SENSORS]
    entities += [BayrolIntervalSummary(coordinator, "interval_summary", n) for n in coordinator.data.intervals]
    async_add_entities(entities)


class BayrolSensor(BayrolEntity, SensorEntity):
    entity_description: BayrolSensorDescription

    def __init__(self, coordinator, description: BayrolSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "daily_filtration":
            return None
        data = self.coordinator.data
        return {
            "per_day": {day: data.daily_filtration_hours(i) for i, day in enumerate(WEEKDAYS)},
        }


class BayrolIntervalSummary(BayrolIntervalEntity, SensorEntity):
    """Human-readable interval summary, e.g. "Monday - Sunday, 10:00-18:00, Normal mode"."""

    @property
    def native_value(self) -> str | None:
        iv = self.interval
        if iv.label:
            label = str(iv.label)
            if "(" in label and label.endswith(")"):
                return label[label.index("(") + 1 : -1]
            return label
        if not iv.enabled:
            return "Off"
        return f"{iv.start:%H:%M}-{iv.end:%H:%M}" if iv.start and iv.end else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        iv = self.interval
        return {
            "active": iv.enabled,
            "start": iv.start.strftime("%H:%M") if iv.start else None,
            "end": iv.end.strftime("%H:%M") if iv.end else None,
            "duration_h": iv.duration_hours,
            "mode": INTERVAL_MODES_REV.get(iv.mode),
            "days": [d for i, d in enumerate(WEEKDAYS) if iv.days and iv.days & (1 << i)],
        }
