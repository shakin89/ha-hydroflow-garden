"""Setup from YAML import, entities, seeding, IU writer, engine events."""

from __future__ import annotations

import copy
import re
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
    await async_setup_component(hass, DOMAIN, {DOMAIN: topo})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


async def test_import_creates_entities_and_seeds(hass: HomeAssistant) -> None:
    hass.states.async_set("input_boolean.iu_alpha_p1_z1_tue", "on")
    hass.states.async_set("input_number.iu_alpha_p1_z1_duration", "17.0")
    hass.states.async_set("input_datetime.iu_alpha_p1_time", "05:30:00")
    reload_calls = _capture(hass, "irrigation_unlimited", "reload")
    Path(hass.config.path("irrigation_unlimited.yaml")).unlink(missing_ok=True)  # left by 0.4.0-beta.2 runs
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

    # engine on: the integration never writes the IU file nor reloads IU
    assert not Path(hass.config.path("irrigation_unlimited.yaml")).exists()
    assert reload_calls == []


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


MASTER_A = "binary_sensor.irrigation_unlimited_c1_m"
IU_SERVICES = ("load_schedule", "enable", "disable", "adjust_time", "reload")


def _iu_calls(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    return {s: _capture(hass, "irrigation_unlimited", s) for s in IU_SERVICES}


def _rt(hass: HomeAssistant):
    return hass.config_entries.async_entries(DOMAIN)[0].runtime_data


MASTER_B = "binary_sensor.irrigation_unlimited_c2_m"
MASTER_EXTRA = "binary_sensor.irrigation_unlimited_c3_m"


def _iu_loads(hass: HomeAssistant, digest: str | None, digest_b: str | None = "current") -> None:
    """IU creates (or reloads) its controllers from a file: alpha with
    ``digest``, beta with ``digest_b`` ("current" = in sync, None = absent)."""
    from custom_components.hydroflow_garden.iu_config import STRUCTURE_ATTR
    hass.states.async_set(MASTER_A, "off", {STRUCTURE_ATTR: digest} if digest else {})
    if digest_b == "current":
        digest_b = _digest(hass, 1)
    if digest_b is None:
        hass.states.async_remove(MASTER_B)
    else:
        hass.states.async_set(MASTER_B, "off", {STRUCTURE_ATTR: digest_b})


def _digest(hass: HomeAssistant, index: int = 0) -> str:
    from custom_components.hydroflow_garden.iu_config import structure_digest
    rt = _rt(hass)
    return structure_digest(rt.get, rt.controller_list[index])


def _outdated_issue(hass: HomeAssistant):
    from homeassistant.helpers import issue_registry as ir
    return ir.async_get(hass).async_get_issue(DOMAIN, "iu_config_outdated")


async def _settle(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()


async def test_sync_pushes_only_changes(hass: HomeAssistant) -> None:
    hass.states.async_set("input_boolean.iu_alpha_p1_z1_enabled", "on")
    hass.states.async_set("input_boolean.iu_alpha_p1_z1_tue", "on")
    calls = _iu_calls(hass)
    await _setup(hass)
    assert not any(calls.values())  # IU has not created the controller yet

    _iu_loads(hass, _digest(hass), digest_b=None)  # alpha only: beta stays outdated
    await _settle(hass)
    loads = list(calls["load_schedule"])
    assert sorted(c.data["schedule_id"] for c in loads) == [f"hf_alpha_s{i}" for i in range(1, 5)]
    assert any(c.data.get("weekday") == ["tue"] and c.data["time"] == "04:00" for c in loads)
    assert {c.data["entity_id"] for c in calls["adjust_time"]} == {MASTER_A}
    assert calls["reload"] == []

    # a duration change sends that duration only
    sent = {k: len(v) for k, v in calls.items()}
    await hass.services.async_call("number", "set_value", {
        "entity_id": "number.iu_alpha_p1_z1_duration", "value": 17}, blocking=True)
    await _settle(hass)
    assert {k: len(v) - sent[k] for k, v in calls.items() if k != "adjust_time"} == {
        "load_schedule": 0, "enable": 0, "disable": 0, "reload": 0}
    new = [c.data for c in calls["adjust_time"][sent["adjust_time"]:]]
    assert new and all(d["zones"] == [1] and d["actual"] == "00:17:00" for d in new)
    assert {sq for d in new for sq in d["sequence_id"]} <= {"1", "2"}  # slots of P1

    # IU reloaded its file: it forgot load_schedule, everything goes again
    await hass.services.async_call("irrigation_unlimited", "reload", {}, blocking=True)
    await _settle(hass)
    assert len(calls["load_schedule"]) == 2 * len(loads)


async def test_outdated_iu_file_is_reported_not_written(hass: HomeAssistant) -> None:
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir

    calls = _iu_calls(hass)
    await _setup(hass)
    _iu_loads(hass, None)  # a file written by 0.4.0-beta.2 or by hand
    await _settle(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "iu_config_outdated")
    assert issue is not None and issue.translation_placeholders["controllers"] == "Controller Alpha"
    pasted = yaml.safe_load(issue.translation_placeholders["yaml"])
    assert pasted["controllers"][0]["user"]["hydroflow_structure"] == _digest(hass)
    assert not [c for c in calls["load_schedule"] if c.data["schedule_id"].startswith("hf_alpha")]
    notes = persistent_notification._async_get_or_create_notifications(hass)
    note = notes[f"{DOMAIN}_iu_config_outdated"]
    assert "Controller Alpha" in note["message"] and "/config/repairs" in note["message"]

    # a dismissed notification does not come back while nothing changes
    persistent_notification.async_dismiss(hass, f"{DOMAIN}_iu_config_outdated")
    await hass.services.async_call("number", "set_value", {
        "entity_id": "number.iu_alpha_p1_z1_duration", "value": 17}, blocking=True)
    await _settle(hass)
    assert f"{DOMAIN}_iu_config_outdated" not in notes

    resp = await hass.services.async_call(DOMAIN, "get_iu_config", {}, blocking=True, return_response=True)
    assert yaml.safe_load(resp["yaml"]) == pasted and resp["in_sync"] == ["Controller Beta"]

    # the user pasted it and reloaded IU
    _iu_loads(hass, _digest(hass))
    await _settle(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "iu_config_outdated") is None
    assert f"{DOMAIN}_iu_config_outdated" not in notes
    assert calls["load_schedule"]


async def test_engine_off_sends_nothing_but_reports_the_file(hass: HomeAssistant) -> None:
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["engine_enabled"] = False
    calls = _iu_calls(hass)
    hass.states.async_set(MASTER_A, "off")
    await _setup(hass, topo)
    await _settle(hass)
    assert not any(calls.values())
    assert _rt(hass).engine is None
    # the YAML to paste is offered before the engine is turned on
    issue = _outdated_issue(hass)
    assert issue is not None
    assert issue.translation_placeholders["controllers"] == "Controller Alpha, Controller Beta"

    _iu_loads(hass, _digest(hass))
    await _settle(hass)
    assert _outdated_issue(hass) is None
    assert not any(calls.values())


async def test_controller_missing_in_iu_is_reported(hass: HomeAssistant) -> None:
    calls = _iu_calls(hass)
    await _setup(hass)
    _iu_loads(hass, _digest(hass), digest_b=None)  # file pasted before beta was added
    await _settle(hass)
    issue = _outdated_issue(hass)
    assert issue is not None and issue.translation_placeholders["controllers"] == "Controller Beta"
    assert calls["load_schedule"]  # alpha is in sync and still gets its schedules


async def test_extra_controller_in_iu_is_reported(hass: HomeAssistant) -> None:
    await _setup(hass)
    _iu_loads(hass, _digest(hass))
    hass.states.async_set(MASTER_EXTRA, "off", {"friendly_name": "Old Cistern"})
    await _settle(hass)
    issue = _outdated_issue(hass)
    assert issue is not None and issue.translation_placeholders["controllers"] == "Old Cistern"

    # the user pasted the current file: IU dropped the old controller
    hass.states.async_remove(MASTER_EXTRA)
    await _settle(hass)
    assert _outdated_issue(hass) is None


async def test_si_adjust_goes_to_the_program_slots(hass: HomeAssistant) -> None:
    hass.states.async_set("input_boolean.iu_alpha_p1_z1_enabled", "on")
    hass.states.async_set("input_boolean.iu_alpha_p1_z1_tue", "on")
    hass.states.async_set("sensor.smart_irrigation_lawn", "900")
    calls = _iu_calls(hass)
    _capture(hass, "smart_irrigation", "update_weather")
    _capture(hass, "smart_irrigation", "calculate")
    await _setup(hass)
    _iu_loads(hass, _digest(hass))
    await _settle(hass)
    rt = _rt(hass)
    ctrl = rt.controller_list[0]
    sent = len(calls["adjust_time"])
    await rt.engine._si_adjust(ctrl, ctrl.programs[0], dt_util.now())
    await hass.async_block_till_done()
    new = [c.data for c in calls["adjust_time"][sent:]]
    assert new and all(d["entity_id"] == MASTER_A and d["zones"] == [1] and d["actual"] == "00:15:00"
                       for d in new)
    assert {sq for d in new for sq in d["sequence_id"]} <= {"1", "2"}  # slots of P1 only
    planned = hass.states.get("sensor.iu_controller_alpha_z1_lawn_programmato")
    assert planned.state == "900" and planned.attributes["adjustment"] == "=00:15:00"


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
    assert [v["path"] for v in cfg["views"]] == [
        f"irrigazione-{c}{s}" for c in ("alpha", "beta") for s in ("", "-programmi", "-zone", "-impostazioni")]
    # only the Today view of each controller is in the tab bar
    assert [v["path"] for v in cfg["views"] if not v.get("subview")] == ["irrigazione-alpha", "irrigazione-beta"]
    sub = next(v for v in cfg["views"] if v.get("subview"))
    assert sub["back_path"] == "/hydroflow-garden/irrigazione-alpha" and "visible" not in sub
    for name in ("hf_base", "hf_hero", "hf_zone_days", "hf_stepper", "hf_appearance"):
        assert name in cfg["button_card_templates"]
    text = yaml.safe_dump(cfg)
    assert "input_boolean" not in text and "input_number" not in text
    assert "switch.iu_alpha_p1_z1_mon" in text
    # button-card (+ optional apexcharts) only
    cards = set(re.findall(r"custom:[a-z-]+", text))
    assert cards == {"custom:button-card", "custom:apexcharts-card"}
    # the navigation of each view points at the dashboard URL
    assert "/hydroflow-garden/irrigazione-alpha-zone" in text
    # no fill / preflight cards for a controller without them
    beta = yaml.safe_dump([v for v in cfg["views"] if v["path"].startswith("irrigazione-beta")])
    assert "fill_lead" not in beta and "preflight" not in beta


async def test_dashboard_warns_when_engine_off() -> None:
    from custom_components.hydroflow_garden.dashboard import render_dashboard
    from custom_components.hydroflow_garden.model import Controller

    ctrls = [Controller.from_dict(c) for c in TOPOLOGY["controllers"]]
    texts = _texts("en")

    def notices(cfg) -> dict[str, list]:
        return {v["path"]: [c for sec in v["sections"] for c in sec.get("cards", [])
                            if c.get("template") == "hf_notice"] for v in cfg["views"]}

    assert not any(notices(render_dashboard(ctrls, "T", texts)).values())
    off = notices(render_dashboard(ctrls, "T", texts, engine_enabled=False))
    assert {p for p, n in off.items() if n} == {
        f"irrigazione-{c}{s}" for c in ("alpha", "beta") for s in ("", "-programmi")}
    card = off["irrigazione-alpha"][0]
    assert card["variables"]["path"] == "/config/integrations/integration/hydroflow_garden"
    assert card["variables"]["title"] == texts["engine_off"]


async def test_manual_fill_ends_after_duration_engine_off(hass: HomeAssistant) -> None:
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["engine_enabled"] = False
    turn_off = _capture(hass, "homeassistant", "turn_off")
    hass.states.async_set("switch.fill_a", "off")
    await _setup(hass, topo)
    assert _rt(hass).engine is None

    hass.states.async_set("switch.fill_a", "on")  # "Fill now" toggle
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=89))
    await hass.async_block_till_done()
    assert turn_off == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=91))
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in turn_off] == [["switch.fill_a"]]


async def test_fill_end_survives_a_reload(hass: HomeAssistant) -> None:
    turn_off = _capture(hass, "homeassistant", "turn_off")
    hass.states.async_set("switch.fill_a", "on")
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=60))
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert turn_off == []  # a reload does not stop the fill
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=91))
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in turn_off] == [["switch.fill_a"]]


async def test_dashboard_background_follows_appearance() -> None:
    from custom_components.hydroflow_garden.dashboard import render_dashboard
    from custom_components.hydroflow_garden.model import Controller
    from custom_components.hydroflow_garden.palettes import PALETTES

    ctrls = [Controller.from_dict(c) for c in TOPOLOGY["controllers"]]
    forced = render_dashboard(ctrls, "T", _texts("en"), theme="laguna", mode="dark")
    assert {v["background"] for v in forced["views"]} == {PALETTES["laguna"]["dark"]["bg"]}
    for theme, mode in (("system", "dark"), ("laguna", "auto"), (None, None)):
        cfg = render_dashboard(ctrls, "T", _texts("en"), theme=theme, mode=mode)
        assert all("background" not in v for v in cfg["views"]), (theme, mode)


def test_auto_palette_uses_light_dark() -> None:
    from custom_components.hydroflow_garden.palettes import PALETTES, TOKENS

    for theme, pal in PALETTES.items():
        assert set(pal["auto"]) == set(TOKENS), theme
    salvia = PALETTES["salvia"]
    assert salvia["auto"]["primary"] == f"light-dark({salvia['light']['primary']}, {salvia['dark']['primary']})"
    assert "light-dark(rgba(" in salvia["auto"]["shadow"] and "none" not in salvia["auto"]["shadow"]
    assert PALETTES["system"]["auto"] == PALETTES["system"]["light"]  # HA vars already follow HA


async def test_appearance_selects(hass: HomeAssistant) -> None:
    from unittest.mock import AsyncMock, patch

    await _setup(hass)
    theme = hass.states.get("select.iu_dashboard_theme")
    mode = hass.states.get("select.iu_dashboard_mode")
    assert theme.state == "system" and theme.attributes["options"] == ["system", "salvia", "laguna", "terracotta"]
    assert mode.state == "auto" and mode.attributes["options"] == ["auto", "light", "dark"]
    with patch("custom_components.hydroflow_garden.dashboard.async_generate_dashboard",
               new=AsyncMock(return_value=True)) as gen:
        await hass.services.async_call("select", "select_option", {
            "entity_id": "select.iu_dashboard_mode", "option": "dark"}, blocking=True)
        await hass.async_block_till_done()
    assert hass.states.get("select.iu_dashboard_mode").state == "dark"
    gen.assert_awaited_once()
    assert gen.await_args.kwargs == {"force": False}


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
    assert "custom:apexcharts-card" in with_chart and "History, last days" in with_chart
    assert "custom:apexcharts-card" not in without and "History, last days" not in without



async def test_dashboard_never_overwrites_a_foreign_dashboard(hass: HomeAssistant) -> None:
    from unittest.mock import AsyncMock

    import pytest
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import LovelaceStorage
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import issue_registry as ir

    assert await async_setup_component(hass, "lovelace", {})
    await _setup(hass)
    dashboards = hass.data[LOVELACE_DATA].dashboards
    url, own = next((u, d) for u, d in dashboards.items() if (d.config or {}).get("id", "").startswith(f"{DOMAIN}_"))

    # its own dashboard is rewritten in place
    own.async_save = AsyncMock()
    await hass.services.async_call(DOMAIN, "regenerate_dashboard", {}, blocking=True)
    own.async_save.assert_awaited_once()

    # a dashboard created by hand on the same URL (id = url, as the UI does) is left alone
    foreign = LovelaceStorage(hass, {"id": url, "url_path": url, "mode": "storage", "title": "Mine"})
    foreign.async_save = AsyncMock()
    dashboards[url] = foreign
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "regenerate_dashboard", {}, blocking=True)
    foreign.async_save.assert_not_awaited()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "dashboard_url_taken") is not None

    # back to its own dashboard: the issue goes away
    dashboards[url] = own
    await hass.services.async_call(DOMAIN, "regenerate_dashboard", {}, blocking=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "dashboard_url_taken") is None


def test_format_line_with_and_without_duration() -> None:
    from custom_components.hydroflow_garden.logfile import format_line

    line = format_line("valve_on", "Garden", zone="Z1 Lawn", entity="switch.v1", duration=600)
    assert line.endswith("[valve_on] ctrl=Garden zone=Z1 Lawn entity=switch.v1 duration=600s")
    marker = format_line("HA RESTART", "Garden", zone="none", duration=None)
    assert marker.endswith("[HA RESTART] ctrl=Garden zone=none")


async def test_dashboard_lists_notify_targets() -> None:
    """The settings view shows where notifications go and links to the options (#2)."""
    from custom_components.hydroflow_garden.dashboard import render_dashboard
    from custom_components.hydroflow_garden.model import Controller

    ctrls = [Controller.from_dict(TOPOLOGY["controllers"][0])]
    texts = _texts("en")
    with_targets = yaml.safe_dump(render_dashboard(
        ctrls, "T", texts, notify_targets=["notify.phone", "notify.mobile_app_x"]))
    assert "notify.phone, notify.mobile_app_x" in with_targets
    assert "/config/integrations/integration/hydroflow_garden" in with_targets
    assert texts["notify_targets_none"] in yaml.safe_dump(render_dashboard(ctrls, "T", texts))
