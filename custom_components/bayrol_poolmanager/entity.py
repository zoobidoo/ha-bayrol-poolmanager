"""Base entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BayrolCoordinator, TimerInterval


class BayrolEntity(CoordinatorEntity[BayrolCoordinator]):
    """Entity attached to the PoolManager device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BayrolCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="PoolManager",
            manufacturer="Bayrol",
            model="PoolManager",
            configuration_url=f"{coordinator.client.base_url}/webview/p/plants.php"
            if coordinator.client.is_cloud
            else coordinator.client.base_url,
        )


class BayrolIntervalEntity(BayrolEntity):
    """Entity bound to one filter pump timer interval."""

    def __init__(self, coordinator: BayrolCoordinator, key: str, number: int) -> None:
        super().__init__(coordinator, key)
        self.number = number
        self._attr_unique_id = f"{self._attr_unique_id}_{number}"
        self._attr_translation_placeholders = {"n": str(number)}

    @property
    def interval(self) -> TimerInterval:
        return self.coordinator.data.intervals[self.number]
