"""Switches: every on/off value (former input_boolean helpers)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ValueEntity, add_grouped, specs_by_kind
from .model import KIND_SWITCH


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    rt = entry.runtime_data
    add_grouped(async_add_entities, [
        (sid, ValueSwitch(rt, spec, ctrl)) for sid, ctrl, spec in specs_by_kind(rt, KIND_SWITCH)
    ])


class ValueSwitch(ValueEntity, SwitchEntity):
    def __init__(self, rt, spec, ctrl) -> None:
        super().__init__(rt, "switch", spec, ctrl)
        if not spec.schedule:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        return bool(self.stored_value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.set_value(False)
