"""Setup, services without a loaded entry, the value store and the dashboard edges."""

from __future__ import annotations

import copy
import logging
from unittest.mock import patch

import pytest
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.hydroflow_garden import async_setup, dashboard
from custom_components.hydroflow_garden.const import DOMAIN
from custom_components.hydroflow_garden.model import (
    KIND_NUMBER,
    KIND_SELECT,
    KIND_SWITCH,
    KIND_TIME,
    ValueSpec,
)
from custom_components.hydroflow_garden.values import ValueStore, _from_legacy

from .conftest import TOPOLOGY
from .test_init import _rt, _setup


# --- __init__ --------------------------------------------------------------

async def test_yaml_block_is_ignored_once_set_up(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    await _setup(hass)
    with caplog.at_level(logging.WARNING):
        assert await async_setup(hass, {DOMAIN: copy.deepcopy(TOPOLOGY)}) is True
    assert "ignored: the integration is already set up" in caplog.text


async def test_actions_need_a_loaded_entry(hass: HomeAssistant) -> None:
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "get_iu_config", {}, blocking=True,
                                       return_response=True)


async def test_rain_skip_needs_the_engine(hass: HomeAssistant) -> None:
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["engine_enabled"] = False
    await _setup(hass, topo)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "rain_skip", {}, blocking=True,
                                       return_response=True)


async def test_the_retired_write_button_is_removed(hass: HomeAssistant) -> None:
    reg = er.async_get(hass)
    old = reg.async_get_or_create("button", DOMAIN, "iu_write_config")
    await _setup(hass)
    assert reg.async_get(old.entity_id) is None


async def test_language_change_reloads_only_when_the_language_differs(hass: HomeAssistant) -> None:
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)  # same language
        await hass.async_block_till_done()
        reload.assert_not_called()
        hass.config.language = "it" if hass.config.language != "it" else "en"
        hass.bus.async_fire(EVENT_CORE_CONFIG_UPDATE)
        await hass.async_block_till_done()
        reload.assert_called_once_with(entry.entry_id)


async def test_removing_the_entry_deletes_its_stored_values(hass: HomeAssistant) -> None:
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN) == []


# --- values ----------------------------------------------------------------

def _spec(kind: str, **kw) -> ValueSpec:
    return ValueSpec(key="k", kind=kind, tkey="t", icon="mdi:x", default=None, **kw)


def test_from_legacy_conversions() -> None:
    assert _from_legacy(_spec(KIND_SWITCH), "") is None
    assert _from_legacy(_spec(KIND_SWITCH), "on") is True
    assert _from_legacy(_spec(KIND_SWITCH), "maybe") is None
    assert _from_legacy(_spec(KIND_NUMBER, min=0, max=10), "50") == 10
    assert _from_legacy(_spec(KIND_NUMBER), "abc") is None
    assert _from_legacy(_spec(KIND_TIME), "6:05") == "06:05:00"
    assert _from_legacy(_spec(KIND_TIME), "06:05:09") == "06:05:09"
    assert _from_legacy(_spec(KIND_TIME), "noon") is None
    assert _from_legacy(_spec(KIND_SELECT, options=("fixed",)), "Fisso") == "fixed"
    assert _from_legacy(_spec(KIND_SELECT, options=("fixed",)), "other") is None
    assert _from_legacy(_spec("weird"), "x") is None


async def test_store_seed_order_and_listener_removal(hass: HomeAssistant) -> None:
    store = ValueStore(hass, "edges")
    specs = {
        "a": ValueSpec(key="a", kind=KIND_SWITCH, tkey="t", icon="i", default=False),
        "b": ValueSpec(key="b", kind=KIND_SWITCH, tkey="t", icon="i", default=False,
                       legacy_domain="input_boolean"),
        "c": ValueSpec(key="c", kind=KIND_NUMBER, tkey="t", icon="i", default=5),
    }
    seeded = await store.async_load(specs, {"extra": 1}, {"a": True, "c": "not a number"})
    assert seeded == ["a"]                       # bool seed used; bad seed falls to default
    assert store.get("a") is True and store.get("c") == 5 and store.get("extra") == 1
    hass.states.async_set("input_boolean.missing", "on")
    assert store.get("b") is False               # legacy helper absent: default

    calls: list[str] = []
    remove = store.listen(lambda k, v: calls.append(k), "a")
    remove()
    remove()                                      # a second removal is harmless
    store.set("a", False)
    assert calls == []
    await store.async_remove()


# --- time ------------------------------------------------------------------

async def test_time_entity_sets_a_value(hass: HomeAssistant) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "time", "set_value", {"entity_id": "time.iu_alpha_p1_time", "time": "05:45:00"},
        blocking=True)
    assert hass.states.get("time.iu_alpha_p1_time").state == "05:45:00"


# --- dashboard -------------------------------------------------------------

async def test_dashboard_resource_check(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    dashboard._check_resources(rt, None)                       # unknown: nothing to say
    dashboard._check_resources(rt, ["/hacsfiles/other.js"])    # button-card missing
    from homeassistant.helpers import issue_registry as ir
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_cards") is not None
    dashboard._check_resources(rt, ["/hacsfiles/button-card/button-card.js"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_cards") is None


async def test_dashboard_skips_unchanged_renders_and_missing_lovelace(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    await dashboard.async_generate_dashboard(rt)                # force: always saves
    assert await dashboard.async_generate_dashboard(rt, force=False) is False  # same digest
    with patch.object(dashboard, "_async_get_or_register", return_value=None):
        assert await dashboard.async_generate_dashboard(rt, force=False) is False


async def test_dashboard_failures_never_break_setup_or_theme_changes(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(dashboard, "async_generate_dashboard", side_effect=RuntimeError("boom")):
        await _setup(hass)
        assert "Dashboard generation failed" in caplog.text
        caplog.clear()
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": "select.iu_dashboard_theme", "option": "laguna"}, blocking=True)
        await hass.async_block_till_done()
        assert "Dashboard generation failed" in caplog.text


async def test_unregister_without_lovelace_data(hass: HomeAssistant) -> None:
    await _setup(hass)
    rt = _rt(hass)
    rt.dashboard_registered = "irr-test"
    with patch.object(dashboard, "_lovelace", return_value=None):
        dashboard._unregister(rt)
