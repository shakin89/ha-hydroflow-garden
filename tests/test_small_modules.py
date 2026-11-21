"""Logfile, notify, planning, button and number: the parts the engine tests skip."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.hydroflow_garden import planning
from custom_components.hydroflow_garden.const import DOMAIN
from custom_components.hydroflow_garden.logfile import LogFile
from custom_components.hydroflow_garden.model import Controller, Program, Zone
from custom_components.hydroflow_garden.notify import async_notify

from .test_init import _capture, _rt, _setup


# --- logfile ---------------------------------------------------------------

async def test_logfile_rotates_and_keeps_copies(hass: HomeAssistant, tmp_path: Path) -> None:
    log = LogFile(hass, str(tmp_path / "irr.log"), max_mb=0.0001, keep=2)  # ~104 bytes
    line = "x" * 120
    for _ in range(5):
        await log.async_write(line)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["irr.log", "irr.log.1", "irr.log.2"]


async def test_logfile_without_copies_truncates(hass: HomeAssistant, tmp_path: Path) -> None:
    log = LogFile(hass, str(tmp_path / "irr.log"), max_mb=0.0001, keep=0)
    for _ in range(3):
        await log.async_write("y" * 120)
    assert [p.name for p in tmp_path.iterdir()] == ["irr.log"]
    assert (tmp_path / "irr.log").read_text().count("\n") == 1


async def test_logfile_relative_path_and_write_error(
    hass: HomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log = LogFile(hass, "logs/irr.log", max_mb=1, keep=1)
    assert log.path == Path(hass.config.path("logs/irr.log"))
    (tmp_path / "irr.log").mkdir()  # a directory: opening it for append fails
    bad = LogFile(hass, str(tmp_path / "irr.log"), max_mb=1, keep=1)
    await bad.async_write("line")
    assert "Cannot write" in caplog.text


# --- notify ----------------------------------------------------------------

async def test_notify_reaches_every_channel_and_survives_failures(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    entity_calls = _capture(hass, "notify", "send_message")
    phone_calls = _capture(hass, "notify", "mobile_app_phone")
    persistent = _capture(hass, "persistent_notification", "create")

    async def broken(call: ServiceCall) -> None:
        raise RuntimeError("boom")

    hass.services.async_register("notify", "broken", broken)
    options = {
        "notify_entities": ["notify.bot"],
        "notify_services": ["notify.broken", "notify.mobile_app_phone", "nodot", ""],
        "notify_persistent": True,
    }
    await async_notify(hass, options, "T", "M")
    assert entity_calls[0].data["entity_id"] == ["notify.bot"]
    assert phone_calls[0].data == {"title": "T", "message": "M"}
    assert persistent[0].data == {"title": "T", "message": "M"}
    assert "Notification via notify.broken failed" in caplog.text


async def test_notify_with_no_channel_does_nothing(hass: HomeAssistant) -> None:
    await async_notify(hass, {}, "T", "M")


# --- planning --------------------------------------------------------------

def _ctrl(*zones: Zone) -> Controller:
    return Controller(id="c", name="C", iu_controller_id="c", entity_id="switch.p",
                      zones=zones, programs=(Program(1, "P"),))


def test_parse_seconds() -> None:
    assert planning.parse_seconds(None) == 0
    assert planning.parse_seconds(90) == 90
    assert planning.parse_seconds(12.7) == 12
    assert planning.parse_seconds("0:01:30") == 90
    assert planning.parse_seconds("10:00") == 600
    assert planning.parse_seconds("a:b") == 0
    assert planning.parse_seconds("45") == 45
    assert planning.parse_seconds("nope") == 0


def test_si_adjust_seconds() -> None:
    assert planning.si_adjust_seconds("600", 2) == 300
    assert planning.si_adjust_seconds("bad", 2) == 0
    assert planning.si_adjust_seconds(None, 1) == 0
    assert planning.si_adjust_seconds("-30", 1) == 0
    assert planning.si_adjust_seconds("90", 0) == 90


def test_zones_to_reset() -> None:
    z1 = Zone(1, "a", "switch.a", "sensor.a")
    z2 = Zone(2, "b", "switch.b", "sensor.b")
    z3 = Zone(3, "c", "switch.c")  # no Smart Irrigation
    ctrl = _ctrl(z1, z2, z3)
    start = [{"zone_id": 1, "duration": "0:10:00"}, {"zone_id": 2, "duration": "0:10:00"},
             {"zone_id": 3, "duration": "0:10:00"}, {"zone_id": "x", "duration": "1"},
             {"zone_id": None, "duration": "1"}]
    finish = [{"zone_id": 1, "duration": "0:09:30"}, {"zone_id": 2, "duration": "0:05:00"}]
    assert planning.zones_to_reset(ctrl, start, finish, True) == [z1]
    assert planning.zones_to_reset(ctrl, start, finish, False) == []
    assert planning.zones_to_reset(ctrl, None, None, True) == []


def test_suspend_seconds_counts_enabled_zones_and_eco() -> None:
    ctrl = _ctrl(Zone(1, "a", "switch.a"), Zone(2, "b", "switch.b"))
    state = {
        "iu_c_p1_z1_enabled": True, "iu_c_p1_z1_mon": True,
        "iu_c_p1_z1_duration": 5,
        "iu_c_p1_z2_enabled": True, "iu_c_p1_z2_mon": False,
        "iu_c_p1_z2_duration": 7,
        "iu_c_p1_eco": True, "iu_c_p1_eco_cycles": 3,
        "iu_c_p1_eco_soak": 60,
    }
    monday = datetime(2026, 11, 23, 6, 0)
    base = planning.suspend_seconds(state.get, ctrl, ctrl.programs[0], monday)
    no_eco = planning.suspend_seconds({**state, "iu_c_p1_eco": False}.get,
                                      ctrl, ctrl.programs[0], monday)
    assert base - no_eco == 180
    assert no_eco - planning.PREFLIGHT_SUSPEND_MARGIN == 300


def test_si_zones_of_program() -> None:
    z1 = Zone(1, "a", "switch.a", "sensor.a")
    z2 = Zone(2, "b", "switch.b")
    ctrl = _ctrl(z1, z2)
    state = {"iu_c_p1_z1_enabled": True, "iu_c_p1_z2_enabled": True,
             "iu_c_p1_enabled": True}
    for z in (1, 2):
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            state[f"iu_c_p1_z{z}_{day}"] = True
        state[f"iu_c_p1_z{z}_duration"] = 10
    assert planning.si_zones_of_program(state.get, ctrl, ctrl.programs[0]) == [z1]


# --- button and number -----------------------------------------------------

async def test_test_button_runs_every_zone(hass: HomeAssistant) -> None:
    calls = _capture(hass, "irrigation_unlimited", "manual_run")
    await _setup(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.iu_alpha_test"}, blocking=True)
    assert len(calls) == 2
    assert all("time" in c.data for c in calls)


async def test_dashboard_button_regenerates(hass: HomeAssistant) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.iu_regenerate_dashboard"}, blocking=True)


async def test_number_sets_and_reads_back(hass: HomeAssistant) -> None:
    await _setup(hass)
    entity = "number.iu_alpha_p1_z1_duration"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity, "value": 12}, blocking=True)
    assert float(hass.states.get(entity).state) == 12.0
    _rt(hass).values.set("iu_alpha_p1_z1_duration", "not a number")
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "unknown"
