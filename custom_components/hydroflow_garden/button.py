"""Buttons: per-controller test run, hub maintenance actions."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import IU_DOMAIN
from .entity import ManagerEntity, add_grouped
from .iu_config import _num, fmt_duration
from .model import eid


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    rt = entry.runtime_data
    items = [(sid, TestButton(rt, ctrl)) for sid, ctrl in rt.controllers]
    items += [(None, DashboardButton(rt))]
    add_grouped(async_add_entities, items)


class TestButton(ManagerEntity, ButtonEntity):
    """Run every zone of the controller for the test duration (per zone, not
    on the controller: a manual_run on the controller does nothing when no
    sequence is active)."""

    def __init__(self, rt, ctrl) -> None:
        super().__init__(rt, "button", eid(ctrl.id, "test"), "test", "mdi:test-tube", ctrl)

    async def async_press(self) -> None:
        secs = int(_num(self.rt.get(eid(self.ctrl.id, "test_duration")), 30))
        for z in self.ctrl.zones:
            await self.hass.services.async_call(IU_DOMAIN, "manual_run", {
                "entity_id": self.rt.zone_entity(self.ctrl, z.id),
                "time": fmt_duration(secs),
            }, blocking=True)


class DashboardButton(ManagerEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, rt) -> None:
        super().__init__(rt, "button", "iu_regenerate_dashboard", "regenerate_dashboard",
                         "mdi:view-dashboard-edit", None)

    async def async_press(self) -> None:
        from .dashboard import async_generate_dashboard
        await async_generate_dashboard(self.rt)
