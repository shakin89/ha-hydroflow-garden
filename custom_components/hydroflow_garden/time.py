"""Program start times (former input_datetime helpers)."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .entity import ValueEntity, add_grouped, specs_by_kind
from .model import KIND_TIME


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    rt = entry.runtime_data
    add_grouped(async_add_entities, [
        (sid, ValueTime(rt, spec, ctrl)) for sid, ctrl, spec in specs_by_kind(rt, KIND_TIME)
    ])


class ValueTime(ValueEntity, TimeEntity):
    def __init__(self, rt, spec, ctrl) -> None:
        super().__init__(rt, "time", spec, ctrl)

    @property
    def native_value(self) -> time | None:
        return dt_util.parse_time(str(self.stored_value))

    async def async_set_value(self, value: time) -> None:
        self.set_value(value.strftime("%H:%M:%S"))
