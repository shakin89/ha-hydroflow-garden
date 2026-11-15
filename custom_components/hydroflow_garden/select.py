"""Selects: program time type, dashboard status tab."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ValueEntity, add_grouped, specs_by_kind
from .model import KIND_SELECT


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    rt = entry.runtime_data
    add_grouped(async_add_entities, [
        (sid, ValueSelect(rt, spec, ctrl)) for sid, ctrl, spec in specs_by_kind(rt, KIND_SELECT)
    ])


class ValueSelect(ValueEntity, SelectEntity):
    def __init__(self, rt, spec, ctrl) -> None:
        super().__init__(rt, "select", spec, ctrl)
        self._attr_options = list(spec.options)

    @property
    def current_option(self) -> str | None:
        return self.value if self.value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        self.set_value(option)
