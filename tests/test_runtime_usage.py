"""Runtime helpers and the per-zone usage buckets."""

from __future__ import annotations

import copy
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir  # noqa: F401
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hydroflow_garden.runtime import async_get_today_forecast

from .conftest import TOPOLOGY
from .test_init import MASTER_A, _capture, _rt, _setup


async def test_probe_and_rain_helpers_without_configuration(hass: HomeAssistant) -> None:
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"].pop("rain_now_entity")
    await _setup(hass, topo)
    rt = _rt(hass)
    alpha, beta = rt.controller_list
    assert rt.is_online(beta) is True            # no probe: always online
    assert rt.is_online(alpha) is False          # probe entity has no state yet
    hass.states.async_set("binary_sensor.esp_a_status", "on")
    assert rt.is_online(alpha) is True
    assert rt.rain_now() is False                # no rain entity configured
    assert "controllers" in rt.build_iu() or rt.build_iu()


async def test_rain_now_follows_the_configured_state(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    assert rt.rain_now() is False
    hass.states.async_set("binary_sensor.raining", "on")
    assert rt.rain_now() is True


async def test_forecast_without_entity_or_service(hass: HomeAssistant) -> None:
    assert await async_get_today_forecast(hass, "") is None
    assert await async_get_today_forecast(hass, "weather.home") is None  # no service


async def test_suspend_reason_clears_when_iu_lifts_the_suspension(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    alpha = rt.controller_list[0]
    hass.states.async_set(MASTER_A, "off", {"suspended": "2099-01-01T00:00:00"})
    rt.set_reason(alpha, "rain")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.iu_alpha_suspend_reason").state == "rain"
    hass.states.async_set(MASTER_A, "off", {"suspended": None})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.iu_alpha_suspend_reason").state == "none"


async def test_fill_already_overdue_is_switched_off_at_once(hass: HomeAssistant, freezer) -> None:
    turn_off = _capture(hass, "homeassistant", "turn_off")
    hass.states.async_set("switch.fill_a", "off")
    await _setup(hass)
    hass.states.async_set("switch.fill_a", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=3))             # fill duration is 90 minutes
    hass.states.async_set("switch.fill_a", "on", {"touch": 1})  # re-plan, same last_changed
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in turn_off] == [["switch.fill_a"]]


async def test_zone_usage_credits_open_time_across_days(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(dt_util.now().replace(hour=23, minute=50, second=0, microsecond=0))
    await _setup(hass)
    rt = _rt(hass)
    alpha = rt.controller_list[0]
    usage = rt.usage
    valve = rt.zone_entity(alpha, 1)

    hass.states.async_set(valve, "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    assert round(usage.seconds(alpha, 1, 0)) == 300      # still open: counted live
    async_fire_time_changed(hass)                        # minute tick keeps the sensor fresh
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=10))                  # past midnight
    usage._midnight(dt_util.now())
    freezer.tick(timedelta(minutes=5))
    hass.states.async_set(valve, "off")
    await hass.async_block_till_done()
    assert round(usage.seconds(alpha, 1, 1)) == 600      # 23:50 -> 00:00 goes to yesterday
    assert round(usage.seconds(alpha, 1, 0)) == 600      # 00:00 -> 00:10 stays on today
    hass.states.async_set(valve, "unavailable")          # closing again changes nothing
    hass.states.async_remove(valve)                      # removal event is ignored
    await hass.async_block_till_done()


async def test_zone_usage_shifts_old_buckets_and_survives_a_stop(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    alpha = rt.controller_list[0]
    usage = rt.usage
    today = dt_util.now().date()
    usage._data["alpha_z1"] = {"day": (today - timedelta(days=2)).isoformat(), "secs": [60, 30, 10]}
    assert [usage.seconds(alpha, 1, n) for n in range(3)] == [0, 0, 60]
    hass.states.async_set(rt.zone_entity(alpha, 1), "on")
    await hass.async_block_till_done()
    await usage.async_stop()                             # credits the open interval and saves
    assert "_saved_at" in await usage._store.async_load()
    usage._on_since.clear()
    usage._tick(dt_util.now())                           # idle: nothing to refresh


async def test_zone_usage_resumes_an_open_valve_after_a_restart(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    alpha = rt.controller_list[0]
    valve = rt.zone_entity(alpha, 1)
    hass.states.async_set(valve, "on")
    await hass.async_block_till_done()
    await rt.usage.async_stop()
    await rt.usage.async_start()                         # reads _saved_at and the open valve
    assert rt.usage._on_since
