"""Setup from YAML import, entities, seeding, IU writer, engine events."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hydroflow_garden import i18n
from custom_components.hydroflow_garden.const import DOMAIN

from .conftest import TOPOLOGY


def _texts(lang: str) -> dict:
    return i18n.load(lang)["dashboard"]


def _capture(hass: HomeAssistant, domain: str, service: str) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register(domain, service, handler)
    return calls


async def _setup(hass: HomeAssistant, topology=None) -> None:
    topo = copy.deepcopy(topology or TOPOLOGY)
    topo["options"]["iu_config_path"] = hass.config.path("iu_test.yaml")
    Path(topo["options"]["iu_config_path"]).unlink(missing_ok=True)
    await async_setup_component(hass, DOMAIN, {DOMAIN: topo})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


async def test_import_creates_entities_and_seeds(hass: HomeAssistant) -> None:
    hass.states.async_set("input_boolean.iu_alpha_p1_z1_tue", "on")
    hass.states.async_set("input_number.iu_alpha_p1_z1_duration", "17.0")
    hass.states.async_set("input_datetime.iu_alpha_p1_time", "05:30:00")
    reload_calls = _capture(hass, "irrigation_unlimited", "reload")
    await _setup(hass)

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert len(entries[0].subentries) == 2

    assert hass.states.get("switch.iu_alpha_p1_z1_tue").state == "on"  # seeded
    assert hass.states.get("switch.iu_alpha_p1_z1_thu").state == "off"  # default
    assert float(hass.states.get("number.iu_alpha_p1_z1_duration").state) == 17.0
    assert hass.states.get("time.iu_alpha_p1_time").state == "05:30:00"
    assert hass.states.get("select.iu_alpha_p1_time_type").state == "fixed"
    assert hass.states.get("switch.iu_alpha_preflight") is not None
    assert hass.states.get("switch.iu_beta_preflight") is None  # no probe configured
    assert hass.states.get("number.iu_alpha_fill_lead_minutes") is not None
    assert hass.states.get("sensor.iu_alpha_suspend_reason").state == "none"
    assert hass.states.get("sensor.iu_controller_alpha_z1_lawn_oggi") is not None
    assert hass.states.get("sensor.iu_controller_alpha_z1_lawn_programmato") is not None
    assert hass.states.get("button.iu_alpha_test") is not None

    # engine on: IU file written and IU reloaded at setup
    path = Path(hass.config.path("iu_test.yaml"))
    cfg = yaml.safe_load(path.read_text())
    assert [c["controller_id"] for c in cfg["controllers"]] == ["controller_alpha", "controller_beta"]
    assert len(reload_calls) == 1


async def test_import_seed_values(hass: HomeAssistant) -> None:
    topo = copy.deepcopy(TOPOLOGY)
    topo["values"] = {"iu_alpha_p1_z2_sat": True, "iu_alpha_p1_eco_cycles": 3,
                      "iu_alpha_p1_time": "13:30:00", "iu_alpha_p1_time_type": "Alba"}
    hass.states.async_set("input_number.iu_alpha_p1_eco_cycles", "4.0")  # import wins
    await _setup(hass, topo)
    assert hass.states.get("switch.iu_alpha_p1_z2_sat").state == "on"
    assert float(hass.states.get("number.iu_alpha_p1_eco_cycles").state) == 3
    assert hass.states.get("time.iu_alpha_p1_time").state == "13:30:00"
    # legacy Italian label in the import -> option code
    assert hass.states.get("select.iu_alpha_p1_time_type").state == "sunrise"


async def test_value_change_rewrites_iu(hass: HomeAssistant) -> None:
    reload_calls = _capture(hass, "irrigation_unlimited", "reload")
    await _setup(hass)
    path = Path(hass.config.path("iu_test.yaml"))
    await hass.services.async_call("switch", "turn_on",
                                   {"entity_id": "switch.iu_alpha_p1_enabled"}, blocking=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    cfg = yaml.safe_load(path.read_text())
    assert all(s["enabled"] for s in cfg["controllers"][0]["sequences"] if s["name"].startswith("P1 "))
    assert len(reload_calls) == 2


async def test_engine_off_writes_nothing(hass: HomeAssistant) -> None:
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["engine_enabled"] = False
    await _setup(hass, topo)
    assert not Path(hass.config.path("iu_test.yaml")).exists()
    assert hass.config_entries.async_entries(DOMAIN)[0].runtime_data.engine is None


async def test_rain_cancel_and_si_reset(hass: HomeAssistant) -> None:
    cancel = _capture(hass, "irrigation_unlimited", "cancel")
    set_bucket = _capture(hass, "smart_irrigation", "set_bucket")
    _capture(hass, "notify", "send_message")
    hass.states.async_set("binary_sensor.esp_a_status", "on")
    await _setup(hass)

    seq = "binary_sensor.irrigation_unlimited_c1_s1"
    start = {"controller": {"index": 0}, "sequence": {"name": "P1 Morning #1"},
             "schedule": {"index": 0}, "entity_id": seq, "run": {"duration": 1200},
             "zones": [{"zone_id": 1, "duration": 600}, {"zone_id": 2, "duration": 600}]}

    # dry: run goes, finish delivering 95% resets the SI bucket of zone 1 only
    hass.bus.async_fire("irrigation_unlimited_start", start)
    await hass.async_block_till_done()
    assert cancel == []
    finish = {**start, "zones": [{"zone_id": 1, "duration": 570}, {"zone_id": 2, "duration": 600}]}
    hass.bus.async_fire("irrigation_unlimited_finish", finish)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in set_bucket] == ["sensor.smart_irrigation_lawn"]

    # raining: scheduled run cancelled
    hass.states.async_set("binary_sensor.raining", "on")
    hass.bus.async_fire("irrigation_unlimited_start", start)
    await hass.async_block_till_done()
    assert len(cancel) == 1


async def test_preflight_cancel_when_offline(hass: HomeAssistant) -> None:
    cancel = _capture(hass, "irrigation_unlimited", "cancel")
    notify = _capture(hass, "notify", "send_message")
    hass.states.async_set("binary_sensor.esp_a_status", "off")
    await _setup(hass)
    hass.bus.async_fire("irrigation_unlimited_start", {
        "controller": {"index": 0}, "sequence": {"name": "P1 Morning #1"},
        "schedule": {"index": None}, "entity_id": "binary_sensor.irrigation_unlimited_c1_s1",
        "zones": []})
    await hass.async_block_till_done()
    assert len(cancel) == 1
    assert "CANCELLED" in notify[0].data["message"]


async def test_fill_fires_before_iu_start(hass: HomeAssistant) -> None:
    turn_on = _capture(hass, "homeassistant", "turn_on")
    hass.states.async_set("switch.fill_a", "off")
    hass.states.async_set("binary_sensor.esp_a_status", "on")
    start = dt_util.now() + timedelta(hours=3)
    hass.states.async_set("binary_sensor.irrigation_unlimited_c1_m", "off", {
        "sequence_status": [{"index": 0, "name": "P1 Morning #1", "start": start.isoformat()}],
        "suspended": None,
    })
    await _setup(hass)
    async_fire_time_changed(hass, start - timedelta(minutes=119))
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    assert turn_on[0].data["entity_id"] == ["switch.fill_a"]


async def test_dashboard_render() -> None:
    from custom_components.hydroflow_garden.dashboard import render_dashboard
    from custom_components.hydroflow_garden.model import Controller

    ctrls = [Controller.from_dict(c) for c in TOPOLOGY["controllers"]]
    cfg = render_dashboard(ctrls, "Irrigazione", _texts("en"))
    assert [v["path"] for v in cfg["views"]] == ["irrigazione-alpha", "irrigazione-beta"]
    assert "iu_zone_row" in cfg["button_card_templates"]
    text = yaml.safe_dump(cfg)
    assert "input_boolean" not in text and "input_number" not in text
    assert "switch.iu_alpha_p1_z1_mon" in text


async def test_preflight_suspends_when_device_stays_offline(hass: HomeAssistant) -> None:
    suspend = _capture(hass, "irrigation_unlimited", "suspend")
    notify = _capture(hass, "notify", "send_message")
    _capture(hass, "homeassistant", "turn_on")
    hass.states.async_set("switch.fill_a", "off")
    hass.states.async_set("binary_sensor.esp_a_status", "off")
    start = dt_util.now() + timedelta(hours=1)
    hass.states.async_set("binary_sensor.irrigation_unlimited_c1_m", "off", {
        "sequence_status": [{"index": 0, "name": "P1 Morning #1", "start": start.isoformat()}],
        "suspended": None,
    })
    await _setup(hass)
    # preflight fires 15 min before, then waits 14 min for the device
    async_fire_time_changed(hass, start - timedelta(minutes=14, seconds=30))
    await hass.async_block_till_done()
    assert suspend == []
    async_fire_time_changed(hass, start - timedelta(seconds=20))
    await hass.async_block_till_done()
    assert len(suspend) == 1
    assert suspend[0].data["entity_id"] == "binary_sensor.irrigation_unlimited_c1_m"
    assert hass.states.get("sensor.iu_alpha_suspend_reason").state == "device_offline"
    assert any("SUSPENDED" in c.data["message"] for c in notify)


async def test_preflight_device_back_in_time(hass: HomeAssistant) -> None:
    suspend = _capture(hass, "irrigation_unlimited", "suspend")
    hass.states.async_set("binary_sensor.esp_a_status", "off")
    start = dt_util.now() + timedelta(hours=1)
    hass.states.async_set("binary_sensor.irrigation_unlimited_c1_m", "off", {
        "sequence_status": [{"index": 0, "name": "P1 Morning #1", "start": start.isoformat()}],
        "suspended": None,
    })
    await _setup(hass)
    async_fire_time_changed(hass, start - timedelta(minutes=14, seconds=30))
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.esp_a_status", "on")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, start - timedelta(seconds=20))
    await hass.async_block_till_done()
    assert suspend == []


async def test_rain_skip(hass: HomeAssistant) -> None:
    suspend = _capture(hass, "irrigation_unlimited", "suspend")
    _capture(hass, "notify", "send_message")

    async def forecasts(call: ServiceCall):
        return {"weather.home": {"forecast": [{"precipitation": 8.0, "precipitation_probability": 90}]}}

    from homeassistant.core import SupportsResponse
    hass.services.async_register("weather", "get_forecasts", forecasts,
                                 supports_response=SupportsResponse.ONLY)
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["weather_entity"] = "weather.home"
    await _setup(hass, topo)
    # nothing active: no suspension
    resp = await hass.services.async_call(DOMAIN, "rain_skip", {}, blocking=True, return_response=True)
    assert resp["skipped"] is False
    await hass.services.async_call("switch", "turn_on", {"entity_id": [
        "switch.iu_beta_system_enabled", "switch.iu_beta_p1_enabled"]}, blocking=True)
    resp = await hass.services.async_call(DOMAIN, "rain_skip", {}, blocking=True, return_response=True)
    assert resp["skipped"] is True
    assert [c.data["entity_id"] for c in suspend] == ["binary_sensor.irrigation_unlimited_c2_m"]
    assert hass.states.get("sensor.iu_beta_suspend_reason").state == "rain"
    assert hass.states.get("sensor.iu_alpha_suspend_reason").state == "none"


async def test_dashboard_render_without_apexcharts() -> None:
    from custom_components.hydroflow_garden.dashboard import render_dashboard
    from custom_components.hydroflow_garden.model import Controller

    ctrls = [Controller.from_dict(c) for c in TOPOLOGY["controllers"]]
    with_chart = yaml.safe_dump(render_dashboard(ctrls, "Irrigazione", _texts("en"), True))
    without = yaml.safe_dump(render_dashboard(ctrls, "Irrigazione", _texts("en"), False))
    assert "apexcharts-card" in with_chart and "Timeline" in with_chart
    assert "apexcharts-card" not in without and "Timeline" not in without

