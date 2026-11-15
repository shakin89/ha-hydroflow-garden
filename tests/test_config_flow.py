"""Config flow: hub entry, controller subentry create + reconfigure."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.irrigation_manager.const import DOMAIN, SUBENTRY_CONTROLLER

HUB = {
    "engine_enabled": False, "notify_persistent": True, "rain_now_state": "on",
    "prob_threshold": 70, "mm_threshold": 3.0, "skip_time": "02:00:00", "skip_hours": 22,
    "log_path": "logs/irrigation.log", "log_max_mb": 50, "log_keep": 3,
    "iu_config_path": "iu_flow_test.yaml", "dashboard_url": "irr-test",
    "dashboard_title": "Irrigazione",
}
CTRL = {
    "name": "Orto", "iu_controller_id": "", "entity_id": "switch.pump",
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
