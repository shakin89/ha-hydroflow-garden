"""Base entities: views on the ValueStore, one device per controller."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .model import Controller, ValueSpec
from .runtime import IrrigationRuntime

HUB_DEVICE = "hub"


def controller_device(entry_id: str, ctrl: Controller) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{ctrl.id}")},
        name=ctrl.name,
        manufacturer="HydroFlow Garden",
        model="Controller",
    )


def hub_device(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{HUB_DEVICE}")},
        name="HydroFlow Garden",
        manufacturer="HydroFlow Garden",
        model="Hub",
    )


class ManagerEntity(Entity):
    """Explicit entity_id = <platform>.<key>, unique_id = key: the object_ids
    of the YAML helpers this integration replaces are kept, whatever the
    entity name. The name is translated: ``tkey`` is the translation_key in
    translations/<lang>.json (entity.<platform>.<tkey>.name)."""

    _attr_should_poll = False
    # Friendly name = device name + entity name (HA composes it).
    _attr_has_entity_name = True

    def __init__(self, rt: IrrigationRuntime, platform: str, key: str, tkey: str,
                 icon: str | None, ctrl: Controller | None,
                 placeholders: dict[str, str] | None = None) -> None:
        self.rt = rt
        self.ctrl = ctrl
        self._key = key
        self.entity_id = f"{platform}.{key}"
        self._attr_unique_id = key
        self._attr_translation_key = tkey
        self._attr_translation_placeholders = placeholders or {}
        self._attr_icon = icon
        self._attr_device_info = (
            controller_device(rt.entry.entry_id, ctrl) if ctrl else hub_device(rt.entry.entry_id)
        )


class ValueEntity(ManagerEntity):
    """Entity bound to one key of the ValueStore."""

    def __init__(self, rt: IrrigationRuntime, platform: str, spec: ValueSpec,
                 ctrl: Controller | None) -> None:
        super().__init__(rt, platform, spec.key, spec.tkey, spec.icon, ctrl, spec.placeholders)
        self.spec = spec

    @property
    def value(self) -> Any:
        return self.rt.values.get(self.spec.key, self.spec.default)

    def set_value(self, value: Any) -> None:
        self.rt.values.set(self.spec.key, value)

    async def async_added_to_hass(self) -> None:
        @callback
        def _changed(_key: str, _value: Any) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self.rt.values.listen(_changed, self.spec.key))


def specs_by_kind(rt: IrrigationRuntime, kind: str):
    """Yield (subentry_id | None, controller | None, spec) of one kind."""
    from .model import controller_specs
    from .runtime import HUB_SPECS

    for spec in HUB_SPECS:
        if spec.kind == kind:
            yield None, None, spec
    for sid, ctrl in rt.controllers:
        for spec in controller_specs(ctrl):
            if spec.kind == kind:
                yield sid, ctrl, spec


def add_grouped(async_add_entities, items) -> None:
    """Add entities, each group under its config subentry (None = hub)."""
    groups: dict[str | None, list] = {}
    for sid, entity in items:
        groups.setdefault(sid, []).append(entity)
    for sid, entities in groups.items():
        if sid is None:
            async_add_entities(entities)
        else:
            async_add_entities(entities, config_subentry_id=sid)
