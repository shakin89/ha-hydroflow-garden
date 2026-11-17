"""iu_config.build_config must match the YAML generator it replaces.

Random helper states over a generic topology are fed to both the reference
builder (verbatim copy, tests/reference) rendered through its original Jinja
template, and to the integration's builder. The parsed YAML must be equal.
"""

from __future__ import annotations

import random
from pathlib import Path

import jinja2
import pytest
import yaml

from custom_components.hydroflow_garden import iu_config
from custom_components.hydroflow_garden.const import LEGACY_OPTIONS
from custom_components.hydroflow_garden.model import (
    KIND_NUMBER,
    KIND_SWITCH,
    Controller,
    Program,
    Zone,
    controller_specs,
)

from .reference import ref_generator as ref

REF_DIR = Path(__file__).parent / "reference"

CONTROLLERS = [
    Controller(
        id="alpha",
        name="Controller Alpha",
        iu_controller_id="controller_alpha",
        entity_id="switch.pump_a",
        zones=tuple(Zone(i, f"Zone {i}", f"switch.valve_a{i}") for i in range(1, 9)),
        programs=(Program(1, "Morning", "04:00"), Program(2, "Evening", "20:00")),
    ),
    Controller(
        id="beta",
        name="Controller Beta",
        iu_controller_id="controller_beta",
        entity_id="switch.pump_b",
        max_zone_duration="01:00",
        zones=tuple(Zone(i, f"Zone {i}", f"switch.valve_b{i}") for i in range(1, 7)),
        programs=(Program(1, "Morning", "08:00"), Program(2, "Afternoon", "13:30")),
    ),
]


def _ref_controllers():
    return [
        ref.Controller(
            id=c.id, name=c.name, iu_controller_id=c.iu_controller_id,
            entity_id=c.entity_id, max_zone_duration=c.max_zone_duration,
            zones=[ref.Zone(z.id, z.name, z.entity_id) for z in c.zones],
            programs=[ref.Program(p.id, p.name, p.default_time) for p in c.programs],
            iu_index=i,
        )
        for i, c in enumerate(CONTROLLERS)
    ]


def _random_states(rng: random.Random) -> tuple[dict[str, str], dict[str, object]]:
    """(legacy HA states, typed values) for the same random configuration."""
    states: dict[str, str] = {}
    values: dict[str, object] = {}
    for ctrl in CONTROLLERS:
        for spec in controller_specs(ctrl):
            if spec.kind == KIND_SWITCH:
                bias = 0.8 if spec.key.endswith("_enabled") else 0.5
                v = rng.random() < bias
                states[f"input_boolean.{spec.key}"] = "on" if v else "off"
                values[spec.key] = v
            elif spec.kind == KIND_NUMBER:
                if spec.key.endswith("_eco_soak"):
                    v = float(rng.choice([0, 10, 30, -20, 600]))
                elif spec.key.endswith("_offset"):
                    v = float(rng.choice([0, 30, -45, 120, -90]))
                else:
                    v = float(rng.randint(int(spec.min), int(spec.max)))
                states[f"input_number.{spec.key}"] = f"{v}"
                values[spec.key] = v
            elif spec.key.endswith("_time_type"):
                # the reference reads the Italian labels, the integration codes
                v = rng.choice(["Fisso", "Alba", "Tramonto"])
                states[f"input_select.{spec.key}"] = v
                values[spec.key] = LEGACY_OPTIONS[v]
            elif spec.key.endswith("_time"):
                v = f"{rng.randint(0, 23):02d}:{rng.choice([0, 15, 30, 45]):02d}:00"
                states[f"input_datetime.{spec.key}"] = v
                values[spec.key] = v
    return states, values


def _render_reference(states: dict[str, str]) -> dict:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(REF_DIR)), keep_trailing_newline=True
    )
    ctx = ref._build_iu_context(_ref_controllers(), states)
    text = env.get_template("iu_reference.yaml.j2").render(**ctx)
    return yaml.safe_load(text)


@pytest.mark.parametrize("seed", range(200))
def test_parity_random(seed: int) -> None:
    rng = random.Random(seed)
    states, values = _random_states(rng)
    expected = _render_reference(states)
    got = iu_config.build_config(values.get, CONTROLLERS)
    assert got == expected


def test_dump_roundtrip() -> None:
    _, values = _random_states(random.Random(1))
    cfg = iu_config.build_config(values.get, CONTROLLERS)
    text = iu_config.dump(cfg)
    assert text.startswith("# AUTO-GENERATED")
    assert yaml.safe_load(text) == cfg
    assert "&id" not in text and "*id" not in text


def _simulate_iu(structure: dict, calls: iu_config.SyncCalls) -> dict:
    """What IU runs after the sync calls, per slot, the way IU applies them
    (load_schedule by schedule_id, enable/disable and adjust_time on
    1-based sequence zones)."""
    seqs = {}
    for s in structure.get("sequences", []):
        sch = s["schedules"][0]
        seqs[s["sequence_id"]] = {
            "schedule": {"id": sch["schedule_id"], "time": sch["time"], "weekday": None,
                         "month": None, "enabled": sch["enabled"]},
            "repeat": s["repeat"], "delay": s["delay"],
            "zones": [{"zone_id": z["zone_id"], "enabled": True, "duration": z["duration"]}
                      for z in s["zones"]],
        }
    by_schedule = {v["schedule"]["id"]: v for v in seqs.values()}
    enabled = True
    for service, data in calls.values():
        if service == "load_schedule":
            sch = by_schedule[data["schedule_id"]]["schedule"]
            sch.update({k: v for k, v in data.items() if k != "schedule_id"})
        elif "sequence_id" not in data:
            if service in ("enable", "disable"):
                enabled = service == "enable"  # adjust_time reset: zone level, not in sequences
        else:
            (slot,) = data["sequence_id"]
            for k in data["zones"]:
                zone = seqs[slot]["zones"][k - 1]
                if service == "adjust_time":
                    zone["duration"] = data["actual"]
                else:
                    zone["enabled"] = service == "enable"
    return {"enabled": enabled, "sequences": seqs}


@pytest.mark.parametrize("seed", range(200))
def test_structure_plus_sync_equals_effective(seed: int) -> None:
    """Pasting build_structure and pushing sync_calls makes IU water exactly
    what build_controller describes."""
    _, values = _random_states(random.Random(seed))
    structure = iu_config.build_structure(values.get, CONTROLLERS)
    for pos, ctrl in enumerate(CONTROLLERS):
        eff = iu_config.build_controller(values.get, ctrl)
        iu = _simulate_iu(structure["controllers"][pos], iu_config.sync_calls(values.get, ctrl))
        assert iu["enabled"] == eff["enabled"]
        eff_seqs = {s["sequence_id"]: s for s in eff.get("sequences", [])}
        assert set(eff_seqs) <= set(iu["sequences"])  # every slot used exists in the file
        for slot, got in iu["sequences"].items():
            want = eff_seqs.get(slot)
            if want is None:
                assert got["schedule"]["enabled"] is False, slot
                continue
            sch = want["schedules"][0]
            assert got["schedule"]["enabled"] == want["enabled"]
            assert got["schedule"]["time"] == sch["time"]
            assert got["schedule"]["weekday"] == sch["weekday"]
            assert got["schedule"]["month"] == (sch.get("month") or list(iu_config.MONTH_CODES))
            assert (got["repeat"], got["delay"]) == (want["repeat"], want["delay"])
            watered = [{"zone_id": z["zone_id"], "duration": z["duration"]}
                       for z in got["zones"] if z["enabled"]]
            assert watered == want["zones"]


def test_structure_is_static() -> None:
    """Only topology and eco shape the structure: times, days, durations,
    months and enable switches do not change the digest."""
    _, values = _random_states(random.Random(3))
    ctrl = CONTROLLERS[0]
    digest = iu_config.structure_digest(values.get, ctrl)
    for key in list(values):
        if "_eco" in key:
            continue
        changed = dict(values)
        v = values[key]
        changed[key] = (not v) if isinstance(v, bool) else ("13:13:00" if isinstance(v, str) else v + 1)
        assert iu_config.structure_digest(changed.get, ctrl) == digest, key
    eco_on = {**values, "iu_alpha_p1_eco": True, "iu_alpha_p1_eco_cycles": 3.0}
    assert iu_config.structure_digest(eco_on.get, ctrl) != iu_config.structure_digest(
        {**eco_on, "iu_alpha_p1_eco_cycles": 4.0}.get, ctrl)


def test_structure_yaml_has_digest_and_unique_schedule_ids() -> None:
    _, values = _random_states(random.Random(5))
    cfg = yaml.safe_load(iu_config.dump(iu_config.build_structure(values.get, CONTROLLERS)))
    ids = [s["schedules"][0]["schedule_id"] for c in cfg["controllers"] for s in c["sequences"]]
    assert len(ids) == len(set(ids))
    for c, ctrl in zip(cfg["controllers"], CONTROLLERS):
        assert c["user"]["hydroflow_structure"] == iu_config.structure_digest(values.get, ctrl)
        assert all(s["schedules"][0]["enabled"] is False for s in c["sequences"])
