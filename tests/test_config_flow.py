"""Config flow: hub entry, controller subentry create + reconfigure."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hydroflow_garden.const import DOMAIN, SUBENTRY_CONTROLLER

from .conftest import TOPOLOGY

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


async def test_default_programs_follow_the_language(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], HUB)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.async_block_till_done()

    def default_names(result) -> list[str]:
        field = next(k for k in result["data_schema"].schema if k == "programs")
        return [p["name"] for p in field.default()]

    for lang, names in (("en", ["Morning", "Evening"]), ("it", ["Mattina", "Sera"])):
        hass.config.language = lang
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_CONTROLLER), context={"source": SOURCE_USER})
        assert default_names(result) == names, lang
        hass.config_entries.subentries.async_abort(result["flow_id"])


def test_validate_assigns_missing_ids() -> None:
    from custom_components.hydroflow_garden.config_flow import _validate_controller
    z = lambda **k: {"name": "z", "entity_id": "switch.v", **k}  # noqa: E731
    data = {**CTRL, "name": "Orto",
            "zones": [z(id=5), z(), z(id=""), z(id=2), z()],
            "programs": [{"name": "a"}, {"name": "b", "id": 4}, {"name": "c"}]}
    out, errors = _validate_controller(data)
    assert errors == {}
    assert [x["id"] for x in out["zones"]] == [2, 5, 6, 7, 8]
    assert [p["id"] for p in out["programs"]] == [4, 5, 6]


def test_validate_id_overflow_and_duplicates() -> None:
    from custom_components.hydroflow_garden.config_flow import _validate_controller
    z = lambda **k: {"name": "z", "entity_id": "switch.v", **k}  # noqa: E731
    _, errors = _validate_controller({**CTRL, "zones": [z(id=99), z()]})
    assert errors == {"zones": "id_overflow"}
    _, errors = _validate_controller({**CTRL, "zones": [z(id=3), z(id=3), z()]})
    assert errors == {"zones": "duplicate_id"}


async def _hub_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], HUB)
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_second_user_flow_is_rejected(hass: HomeAssistant) -> None:
    await _hub_entry(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] in ("single_instance_allowed", "already_configured")


async def test_import_creates_entry_and_second_import_aborts(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=TOPOLOGY)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert {s.data["id"] for s in entry.subentries.values()} == {"alpha", "beta"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=TOPOLOGY)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] in ("single_instance_allowed", "already_configured")


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = await _hub_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**HUB, "prob_threshold": 55})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["prob_threshold"] == 55
    await hass.async_block_till_done()


async def test_controller_flow_errors_then_recovery(hass: HomeAssistant) -> None:
    entry = await _hub_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CONTROLLER), context={"source": SOURCE_USER})
    for bad, expected in (
        ({**CTRL, "zones": []}, {"zones": "no_zones"}),
        ({**CTRL, "programs": []}, {"programs": "no_programs"}),
        ({**CTRL, "programs": [{"id": 1, "name": "a"}, {"id": 1, "name": "b"}]},
         {"programs": "duplicate_id"}),
        ({**CTRL, "programs": [{"id": 9, "name": "a"}, {"name": "b"}]},
         {"programs": "id_overflow"}),
    ):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], bad)
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == expected
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], CTRL)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_duplicate_controller_is_rejected(hass: HomeAssistant) -> None:
    entry = await _hub_entry(hass)
    for expect_ok in (True, False):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_CONTROLLER), context={"source": SOURCE_USER})
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], CTRL)
        if expect_ok:
            assert result["type"] is FlowResultType.CREATE_ENTRY
            await hass.async_block_till_done()
        else:
            assert result["type"] is FlowResultType.FORM
            assert result["errors"] == {"name": "already_configured"}
            hass.config_entries.subentries.async_abort(result["flow_id"])


async def test_reconfigure_error_recovery(hass: HomeAssistant) -> None:
    entry = await _hub_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CONTROLLER), context={"source": SOURCE_USER})
    await hass.config_entries.subentries.async_configure(result["flow_id"], CTRL)
    await hass.async_block_till_done()
    sub = next(iter(entry.subentries.values()))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CONTROLLER),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**CTRL, "zones": []})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"zones": "no_zones"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], CTRL)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
