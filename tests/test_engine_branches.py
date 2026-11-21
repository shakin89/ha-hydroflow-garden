"""Engine: the branches the happy-path tests do not reach."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util

from custom_components.hydroflow_garden import engine as engine_mod

from .conftest import TOPOLOGY
from .test_init import MASTER_A, MASTER_B, _capture, _rt, _setup

ESP_A = "binary_sensor.esp_a_status"
SEQ = "binary_sensor.irrigation_unlimited_c1_s1"


async def _engine(hass: HomeAssistant, topo=None):
    await _setup(hass, topo)
    rt = _rt(hass)
    return rt, rt.engine, rt.controller_list[0], rt.controller_list[1]


async def _activate(hass: HomeAssistant, *names: str) -> None:
    ents = [e for n in names for e in (f"switch.iu_{n}_system_enabled", f"switch.iu_{n}_p1_enabled")]
    await hass.services.async_call("switch", "turn_on", {"entity_id": ents}, blocking=True)


def _event(**kw) -> dict:
    return {"controller": {"index": 0}, "sequence": {"name": "P1 Morning #1"},
            "schedule": {"index": None}, "entity_id": SEQ, "zones": [], **kw}


# --- helpers ---------------------------------------------------------------

def test_parse_start_variants() -> None:
    now = dt_util.now()
    assert engine_mod._parse_start(now) == now
    assert engine_mod._parse_start(now.isoformat()) == now
    assert engine_mod._parse_start("garbage") is None
    assert engine_mod._parse_start("") is None
    assert engine_mod._parse_start(5) is None


async def test_next_starts_picks_the_earliest_valid_entry(hass: HomeAssistant) -> None:
    _, engine, alpha, beta = await _engine(hass)
    assert engine.next_starts(alpha) == {}  # master entity does not exist yet
    soon, later = dt_util.now() + timedelta(hours=1), dt_util.now() + timedelta(hours=5)
    hass.states.async_set(MASTER_A, "off", {"sequence_status": [
        {"name": "P1 Morning #1", "start": later.isoformat()},
        {"name": "P1 Morning #2", "start": soon},          # datetime, earlier: wins
        {"name": "Px broken", "start": soon.isoformat()},   # not a number
        {"name": "Other", "start": soon.isoformat()},       # not a program
        {"name": "P2 Evening", "start": "nope"},            # no usable start
    ]})
    assert engine.next_starts(alpha) == {1: soon}


async def test_call_reports_missing_and_failing_services(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    _, engine, _, _ = await _engine(hass)
    assert await engine._call("nope", "nothing", {}) is False
    assert "not available" in caplog.text

    async def broken(call: ServiceCall) -> None:
        raise RuntimeError("boom")

    hass.services.async_register("test_dom", "broken", broken)
    assert await engine._call("test_dom", "broken", {}) is False
    assert "test_dom.broken failed" in caplog.text


async def test_stop_cancels_timers_and_tasks(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.fill_a", "off")
    hass.states.async_set(ESP_A, "on")
    start = dt_util.now() + timedelta(hours=3)
    hass.states.async_set(MASTER_A, "off", {"sequence_status": [
        {"name": "P1 Morning #1", "start": start.isoformat()}]})
    _, engine, _, _ = await _engine(hass)
    assert engine._timers
    await engine.async_stop()
    assert not engine._timers and not engine._unsubs


async def test_replan_follows_lead_changes_and_drops_stale_timers(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.fill_a", "off")
    start = dt_util.now() + timedelta(hours=5)
    hass.states.async_set(MASTER_A, "off", {"sequence_status": [
        {"name": "P1 Morning #1", "start": start.isoformat()}]})
    rt, engine, _, _ = await _engine(hass)
    before = dict(engine._timers)
    assert before
    rt.values.set("iu_alpha_fill_lead_minutes", 60)  # moves the fire time
    await hass.async_block_till_done()
    assert engine._timers != before
    rt.values.set("iu_alpha_fill_lead_minutes", 0)   # lead <= 0: no timer
    await hass.async_block_till_done()
    assert not any(k[2] == "fill" for k in engine._timers)
    hass.states.async_remove(MASTER_A)
    engine._replan()
    assert not engine._timers


async def test_fire_ignores_done_and_vanished_targets(hass: HomeAssistant) -> None:
    rt, engine, _, _ = await _engine(hass)
    start = dt_util.now() + timedelta(hours=1)
    turn_on = _capture(hass, "homeassistant", "turn_on")
    hass.states.async_set("switch.fill_a", "off")
    hass.states.async_set(ESP_A, "on")
    fire = engine._make_fire("alpha", 1, "fill", start)
    fire(dt_util.now())
    await hass.async_block_till_done()
    fire(dt_util.now())  # the same occurrence again: ignored
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    engine._make_fire("ghost", 1, "fill", start)(dt_util.now())  # unknown controller
    engine._make_fire("alpha", 7, "fill", start)(dt_util.now())  # unknown program
    await hass.async_block_till_done()
    assert len(turn_on) == 1


# --- fill ------------------------------------------------------------------

async def test_fill_skips_when_busy_offline_or_zero_minutes(hass: HomeAssistant) -> None:
    turn_on = _capture(hass, "homeassistant", "turn_on")
    notify = _capture(hass, "notify", "send_message")
    rt, engine, alpha, _ = await _engine(hass)
    prog, start = alpha.programs[0], dt_util.now()

    hass.states.async_set("switch.fill_a", "on")           # already filling
    await engine._fill(alpha, prog, start)
    hass.states.async_set("switch.fill_a", "off")
    hass.states.async_set(ESP_A, "off")                    # device offline
    await engine._fill(alpha, prog, start)
    assert any("fill" in c.data["message"].lower() for c in notify)
    hass.states.async_set(ESP_A, "on")
    rt.values.set("iu_alpha_fill_duration_minutes", 0)     # nothing to fill
    await engine._fill(alpha, prog, start)
    assert turn_on == []


# --- preflight -------------------------------------------------------------

async def test_preflight_does_nothing_when_off_suspended_or_online(hass: HomeAssistant) -> None:
    suspend = _capture(hass, "irrigation_unlimited", "suspend")
    rt, engine, alpha, _ = await _engine(hass)
    prog, start = alpha.programs[0], dt_util.now()
    hass.states.async_set(ESP_A, "off")

    rt.values.set("iu_alpha_preflight", False)
    await engine._preflight(alpha, prog, start)             # switch off
    rt.values.set("iu_alpha_preflight", True)
    hass.states.async_set(MASTER_A, "off", {"suspended": "2026-11-23T08:00:00"})
    await engine._preflight(alpha, prog, start)             # already suspended
    hass.states.async_set(MASTER_A, "off", {"suspended": None})
    hass.states.async_set(ESP_A, "on")
    await engine._preflight(alpha, prog, start)             # online
    assert suspend == []


# --- Smart Irrigation ------------------------------------------------------

async def test_si_adjust_without_si_zones_does_nothing(hass: HomeAssistant) -> None:
    calc = _capture(hass, "smart_irrigation", "calculate")
    _, engine, _, beta = await _engine(hass)
    await engine._si_adjust(beta, beta.programs[0], dt_util.now())
    assert calc == []


async def test_si_hourly_calculates_only_while_idle(hass: HomeAssistant) -> None:
    calc = _capture(hass, "smart_irrigation", "calculate")
    _, engine, _, _ = await _engine(hass)
    hass.states.async_set(MASTER_A, "on")
    engine._si_hourly_cb(dt_util.now())
    await hass.async_block_till_done()
    assert calc == []
    hass.states.async_set(MASTER_A, "off")
    engine._si_hourly_cb(dt_util.now())
    await hass.async_block_till_done()
    assert len(calc) == 1


# --- rain ------------------------------------------------------------------

def _forecast(hass: HomeAssistant, mm: float, prob: int) -> None:
    async def forecasts(call: ServiceCall):
        return {"weather.home": {"forecast": [
            {"precipitation": mm, "precipitation_probability": prob}]}}

    hass.services.async_register("weather", "get_forecasts", forecasts,
                                 supports_response=SupportsResponse.ONLY)


async def test_rain_skip_below_thresholds_and_without_forecast(hass: HomeAssistant) -> None:
    suspend = _capture(hass, "irrigation_unlimited", "suspend")
    _capture(hass, "notify", "send_message")
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["weather_entity"] = "weather.home"
    rt, engine, _, _ = await _engine(hass, topo)
    await _activate(hass, "alpha")
    assert await engine.async_rain_skip() is False          # no forecast service
    _forecast(hass, mm=0.5, prob=10)
    assert await engine.async_rain_skip() is False          # dry day
    assert suspend == []
    assert await engine.async_rain_skip(force=True) is True


async def test_rain_detected_notifies_only_controllers_that_adjust(hass: HomeAssistant) -> None:
    notify = _capture(hass, "notify", "send_message")
    rt, engine, _, _ = await _engine(hass)
    await _activate(hass, "alpha")
    engine._rain_now_cb()                                   # not raining
    await hass.async_block_till_done()
    assert notify == []
    hass.states.async_set("binary_sensor.raining", "on")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.iu_alpha_adjust_rain"}, blocking=True)
    await hass.async_block_till_done()
    notify.clear()
    engine._rain_now_cb()
    await hass.async_block_till_done()
    assert len(notify) == 1


# --- IU events -------------------------------------------------------------

async def test_events_of_unknown_controllers_are_ignored(hass: HomeAssistant) -> None:
    notify = _capture(hass, "notify", "send_message")
    await _engine(hass)
    hass.bus.async_fire("irrigation_unlimited_start", {**_event(), "controller": {"index": 9}})
    hass.bus.async_fire("irrigation_unlimited_finish", {**_event(), "controller": {}})
    await hass.async_block_till_done()
    assert notify == []


async def test_controller_start_finish_cancel_and_valves_are_logged_and_notified(
    hass: HomeAssistant,
) -> None:
    notify = _capture(hass, "notify", "send_message")
    hass.states.async_set(ESP_A, "on")
    rt, engine, _, _ = await _engine(hass)
    lines: list[str] = []

    async def write(line: str) -> None:
        lines.append(line)

    rt.log.async_write = write
    run = {"run": {"duration": 1200}}
    for name in ("start", "finish", "cancel"):
        hass.bus.async_fire(f"irrigation_unlimited_{name}", _event(**run))
    for name, typ in (("on", 2), ("off", 1)):
        hass.bus.async_fire(f"irrigation_unlimited_valve_{name}", _event(
            zone={"name": "Lawn"}, duration=600, type=typ))
    await hass.async_block_till_done()
    joined = "\n".join(lines)
    for tag in ("[ctrl_start]", "[ctrl_finish]", "[valve_on]", "[valve_off]"):
        assert tag in joined
    assert "type=2" in joined
    assert len(notify) == 3


async def test_preflight_cancel_is_logged(hass: HomeAssistant) -> None:
    _capture(hass, "irrigation_unlimited", "cancel")
    _capture(hass, "notify", "send_message")
    hass.states.async_set(ESP_A, "off")
    rt, _, _, _ = await _engine(hass)
    lines: list[str] = []

    async def write(line: str) -> None:
        lines.append(line)

    rt.log.async_write = write
    hass.bus.async_fire("irrigation_unlimited_start", _event())
    await hass.async_block_till_done()
    assert any("[preflight_cancel]" in line for line in lines)


async def test_notifications_switch_silences_run_messages(hass: HomeAssistant) -> None:
    notify = _capture(hass, "notify", "send_message")
    hass.states.async_set(ESP_A, "on")
    await _engine(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.iu_alpha_notifications"}, blocking=True)
    hass.bus.async_fire("irrigation_unlimited_start", _event(run={"duration": 600}))
    await hass.async_block_till_done()
    assert notify == []


async def test_ha_started_replans_and_logs_restart(hass: HomeAssistant) -> None:
    rt, engine, _, _ = await _engine(hass)
    lines: list[str] = []

    async def write(line: str) -> None:
        lines.append(line)

    rt.log.async_write = write
    await engine._ha_started(None)
    assert sum("HA RESTART" in line for line in lines) == 2
