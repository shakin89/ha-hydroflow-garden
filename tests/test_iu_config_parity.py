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
