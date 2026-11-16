"""Translations: generated files, language parity, translated entities,
notifications and dashboard, migration of the old Italian option values."""

from __future__ import annotations

import copy
import importlib.util
import re
import string
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.hydroflow_garden import i18n
from custom_components.hydroflow_garden.const import DOMAIN
from custom_components.hydroflow_garden.dashboard import render_dashboard
from custom_components.hydroflow_garden.model import (
    KIND_SELECT,
    Controller,
    ValueSpec,
)
from custom_components.hydroflow_garden.values import ValueStore

from .conftest import TOPOLOGY

ROOT = Path(__file__).resolve().parent.parent


def _build_script():
    spec = importlib.util.spec_from_file_location("build_translations", ROOT / "scripts" / "build_translations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shape(node):
    """Keys and str.format placeholders, language-independent."""
    if isinstance(node, dict):
        return {k: _shape(v) for k, v in node.items()}
    if isinstance(node, list):
        return len(node)
    return sorted({f for _, f, _, _ in string.Formatter().parse(str(node)) if f})


def test_generated_files_up_to_date() -> None:
    build = _build_script()
    for path, data in build.outputs().items():
        assert path.read_text(encoding="utf-8") == build.render(data), (
            f"{path.relative_to(ROOT)} is stale: run python3 scripts/build_translations.py")
    assert build.LANGS == i18n.LANGUAGES


def test_languages_have_the_same_keys_and_placeholders() -> None:
    build = _build_script()
    base = i18n.DEFAULT_LANGUAGE
    for lang in i18n.LANGUAGES:
        assert _shape(build.build(lang)) == _shape(build.build(base)), lang
        assert _shape(build.build_texts(lang)) == _shape(build.build_texts(base)), lang


def test_language_tag() -> None:
    assert i18n.language("it") == "it"
    assert i18n.language("en-GB") == "en"
    assert i18n.language("de") == "en"
    assert i18n.language(None) == "en"


async def _setup(hass: HomeAssistant, language: str = "en") -> None:
    await hass.config.async_update(language=language)
    topo = copy.deepcopy(TOPOLOGY)
    topo["options"]["iu_config_path"] = hass.config.path("iu_i18n_test.yaml")
    await async_setup_component(hass, DOMAIN, {DOMAIN: topo})
    await hass.async_block_till_done()


def _names(hass: HomeAssistant) -> dict[str, str]:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    ents = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    return {e.entity_id: hass.states.get(e.entity_id).attributes.get("friendly_name") for e in ents}


async def test_every_entity_has_a_translated_name(hass: HomeAssistant) -> None:
    await _setup(hass)
    names = _names(hass)
    assert names
    devices = {"Controller Alpha", "Controller Beta", "HydroFlow Garden"}
    untranslated = [eid for eid, name in names.items() if not name or name in devices or "{" in name]
    assert untranslated == []
    assert names["switch.iu_alpha_p1_z1_mon"] == "Controller Alpha P1 Morning Z1 Lawn Monday"
    assert names["sensor.iu_controller_alpha_z1_lawn_oggi"] == "Controller Alpha Z1 Lawn today"
    assert names["select.iu_alpha_p1_time_type"] == "Controller Alpha P1 Morning time type"


async def test_italian(hass: HomeAssistant) -> None:
    notify: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        notify.append(call)

    hass.services.async_register("notify", "send_message", handler)
    hass.services.async_register("irrigation_unlimited", "cancel", handler)
    hass.states.async_set("binary_sensor.esp_a_status", "off")
    await _setup(hass, "it")
    names = _names(hass)
    assert names["switch.iu_alpha_p1_z1_mon"] == "Controller Alpha P1 Morning Z1 Lawn Lunedì"
    assert names["number.iu_alpha_p1_eco_soak"] == "Controller Alpha P1 Morning pausa eco"

    hass.bus.async_fire("irrigation_unlimited_start", {
        "controller": {"index": 0}, "sequence": {"name": "P1 Morning #1"},
        "schedule": {"index": None}, "entity_id": "binary_sensor.irrigation_unlimited_c1_s1",
        "zones": []})
    await hass.async_block_till_done()
    msgs = [c.data for c in notify if c.domain == "notify"]
    assert msgs[0]["title"] == "Irrigazione"
    assert "ANNULLATA" in msgs[0]["message"]


async def test_language_change_reloads(hass: HomeAssistant) -> None:
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.runtime_data.texts.lang == "en"
    await hass.config.async_update(language="it")
    await hass.async_block_till_done()
    assert entry.runtime_data.texts.lang == "it"


def _render(lang: str) -> str:
    ctrls = [Controller.from_dict(c) for c in TOPOLOGY["controllers"]]
    return yaml.safe_dump(render_dashboard(ctrls, "T", i18n.load(lang)["dashboard"]), allow_unicode=True)


def test_dashboard_languages() -> None:
    en, it = _render("en"), _render("it")
    assert "Next irrigation" in en and "Prossima Irrigazione" in it
    for word in ("Prossima", "Sospeso", "Riprende", "Lun", "Gen"):
        assert not re.search(rf"\b{word}\b", en), word
    # state comparisons use the codes, whatever the language
    for text in (en, it):
        assert "state: fixed" in text and "option: next" in text and "'rain'" in text
        assert "button.iu_alpha_test" not in text  # test mode not in the dashboard


async def test_legacy_option_values_migrated(hass: HomeAssistant, hass_storage) -> None:
    hass_storage[f"{DOMAIN}.x.values"] = {
        "version": 1, "key": f"{DOMAIN}.x.values",
        "data": {"tt": "Alba", "tab": "Storico", "reason": "Pioggia", "other": "Alba"},
    }
    hass.states.async_set("input_select.tt2", "Tramonto")
    sel = {"kind": KIND_SELECT, "icon": "", "legacy_domain": "input_select"}
    specs = {
        "tt": ValueSpec("tt", tkey="time_type", default="fixed",
                        options=("fixed", "sunrise", "sunset"), **sel),
        "tt2": ValueSpec("tt2", tkey="time_type", default="fixed",
                         options=("fixed", "sunrise", "sunset"), **sel),
        "tab": ValueSpec("tab", tkey="status_tab", default="next",
                         options=("next", "history", "smart", "timeline"), **sel),
    }
    store = ValueStore(hass, "x")
    await store.async_load(specs, {"reason": "none"})
    assert store.get("tt") == "sunrise"
    assert store.get("tt2") == "sunset"  # seeded from the legacy helper
    assert store.get("tab") == "history"
    assert store.get("reason") == "rain"
    assert store.get("other") == "Alba"  # not an option value: untouched
