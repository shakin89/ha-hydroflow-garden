"""Rain-now indicator (gates the cancel at start)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_RAIN_NOW_ENTITY
from .entity import ManagerEntity
from .runtime import SIGNAL_RAIN_NOW


PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([RainNow(entry.runtime_data)])


class RainNow(ManagerEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, rt) -> None:
        super().__init__(rt, "binary_sensor", "iu_sta_piovendo", "raining",
                         "mdi:weather-pouring", None)

    @property
    def available(self) -> bool:
        return super().available and bool(self.rt.options.get(CONF_RAIN_NOW_ENTITY))

    @property
    def is_on(self) -> bool:
        return self.rt.rain_now()

    @property
    def extra_state_attributes(self) -> dict:
        return {"source": self.rt.options.get(CONF_RAIN_NOW_ENTITY)}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_RAIN_NOW, self.async_write_ha_state))
