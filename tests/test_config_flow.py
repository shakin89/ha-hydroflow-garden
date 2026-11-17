"""Config flow: hub entry, controller subentry create + reconfigure."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hydroflow_garden.const import DOMAIN, SUBENTRY_CONTROLLER

HUB = {
    "engine_enabled": False, "notify_persistent": True, "rain_now_state": "on",
    "prob_threshold": 70, "mm_threshold": 3.0, "skip_time": "02:00:00", "skip_hours": 22,
    "log_path": "logs/irrigation.log", "log_max_mb": 50, "log_keep": 3,
    "dashboard_url": "irr-test",
    "dashboard_title": "Irrigazione",
}
CTRL = {
    "name": "Orto", "entity_id": "switch.pump",
    "max_zone_duration": "00:30",
    "zones": [{"id": 1, "name": "Pomodori", "entity_id": "switch.v1"},
              {"id": 2, "name": "Insalata", "entity_id": "switch.v2"}],
    "programs": [{"id": 1, "name": "Mattina", "default_time": "06:00:00"}],
    "fill_lead_minutes": 120, "fill_duration_minutes": 90, "preflight_timeout_minutes": 15,
}


async def test_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], HUB)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CONTROLLER), context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    bad = {**CTRL, "zones": [CTRL["zones"][0], {**CTRL["zones"][1], "id": 1}]}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"zones": "duplicate_id"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], CTRL)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    sub = next(iter(entry.subentries.values()))
    assert sub.data["id"] == "orto"
    assert sub.data["iu_controller_id"] == "orto"
    assert sub.data["programs"][0]["default_time"] == "06:00"
    assert hass.states.get("switch.iu_orto_p1_z2_mon") is not None

    # reconfigure: add a zone
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CONTROLLER),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id})
    zones = CTRL["zones"] + [{"id": 3, "name": "Fragole", "entity_id": "switch.v3"}]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**CTRL, "zones": zones})
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert hass.states.get("switch.iu_orto_p1_z3_mon") is not None


async def test_controller_without_fill(hass: HomeAssistant) -> None:
    """Fill switches, lead and duration can all be left empty (#4)."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], HUB)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CONTROLLER), context={"source": SOURCE_USER})
    no_fill = {k: v for k, v in CTRL.items() if not k.startswith("fill_")}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], no_fill)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    sub = next(iter(entry.subentries.values()))
    assert sub.data["fill_switches"] == []
    assert (sub.data["fill_lead_minutes"], sub.data["fill_duration_minutes"]) == (120, 90)
    assert hass.states.get("number.iu_orto_fill_lead_minutes") is None
