"""Numbers: durations, offsets, leads (former input_number helpers)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ValueEntity, add_grouped, specs_by_kind
from .model import KIND_NUMBER


PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    rt = entry.runtime_data
    add_grouped(async_add_entities, [
        (sid, ValueNumber(rt, spec, ctrl)) for sid, ctrl, spec in specs_by_kind(rt, KIND_NUMBER)
    ])


class ValueNumber(ValueEntity, NumberEntity):
    def __init__(self, rt, spec, ctrl) -> None:
        super().__init__(rt, "number", spec, ctrl)
        self._attr_native_min_value = spec.min
        self._attr_native_max_value = spec.max
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_mode = NumberMode.SLIDER if spec.mode == "slider" else NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        try:
            return float(self.stored_value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        self.set_value(float(value))
