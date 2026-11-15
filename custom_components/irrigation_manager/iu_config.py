"""Build the Irrigation Unlimited configuration from topology + values.

Pure Python (only PyYAML, which Home Assistant ships). Ported from
``_build_iu_context`` of the YAML generator; the behaviour is pinned by
tests/test_iu_config_parity.py against that original code.

Rules kept from the generator:

* One IU sequence per *set of zones* watered on a day, carrying the weekdays
  on which exactly that set runs. Every weekday falls in ONE sequence: the
  sequences of a program share its time, and IU would start two sequences on
  the same day in parallel (valves open together).
* ``sequence_id`` slots are fixed: program N owns ``(N-1)*zones+1 ..
  N*zones``. The IU *entity* ``..._s<M>`` is positional, not the sequence_id:
  never derive entity ids from the slot.
* Eco: the zone duration set by the user is the total; it is split over the
  cycles (``repeat``), with ``delay`` = soak seconds between cycles.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import yaml

from .const import (
    HEADER,
    MONTH_CODES,
    TIME_FIXED,
    TIME_SUNRISE,
    TIME_SUNSET,
    WEEKDAY_CODES,
)
from .model import Controller, Program, eid

_LOGGER = logging.getLogger(__name__)

Getter = Callable[[str], Any]


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _num(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def program_repeat(get: Getter, ctrl: Controller, prog: Program) -> int:
    """Cycles IU runs the program for (1 when eco is off)."""
    pn = f"p{prog.id}"
    if not get(eid(ctrl.id, pn, "eco")):
        return 1
    return max(int(_num(get(eid(ctrl.id, pn, "eco_cycles")), 2)), 1)


def _schedule_time(get: Getter, ctrl: Controller, prog: Program) -> str | dict:
    pn = f"p{prog.id}"
    time_type = get(eid(ctrl.id, pn, "time_type")) or TIME_FIXED
    if time_type in (TIME_SUNRISE, TIME_SUNSET):
        offset = int(_num(get(eid(ctrl.id, pn, "offset")), 0))
        out: dict[str, str] = {"sun": "sunrise" if time_type == TIME_SUNRISE else "sunset"}
        if offset:
            mins = abs(offset)
            out["after" if offset > 0 else "before"] = f"{mins // 60:02d}:{mins % 60:02d}"
        return out
    fixed = str(get(eid(ctrl.id, pn, "time")) or prog.default_time)
    return fixed[:5]


def build_controller(get: Getter, ctrl: Controller) -> dict:
    c = ctrl.id
    n_zones = len(ctrl.zones)
    sequences: list[dict] = []

    for p in ctrl.programs:
        pn = f"p{p.id}"
        prog_enabled = bool(get(eid(c, pn, "enabled")))
        eco_on = bool(get(eid(c, pn, "eco")))
        eco_cycles = int(_num(get(eid(c, pn, "eco_cycles")), 2))
        soak = int(_num(get(eid(c, pn, "eco_soak")), 600)) if eco_on else 0
        repeat = max(eco_cycles, 1) if eco_on else 1
        months = [m for m in MONTH_CODES if get(eid(c, pn, m))]
        time_value = _schedule_time(get, ctrl, p)

        zone_days: dict[int, tuple[str, ...]] = {}
        zone_secs: dict[int, int] = {}
        for z in ctrl.zones:
            if not get(eid(c, pn, f"z{z.id}_enabled")):
                continue
            days = tuple(d for d in WEEKDAY_CODES if get(eid(c, pn, f"z{z.id}_{d}")))
            if not days:
                continue
            secs = int(_num(get(eid(c, pn, f"z{z.id}_duration")), 10)) * 60
            if eco_on and eco_cycles > 1:
                secs = max(secs // eco_cycles, 1)
            zone_days[z.id] = days
            zone_secs[z.id] = secs

        sets_to_days: dict[tuple[int, ...], list[str]] = {}
        for d in WEEKDAY_CODES:
            day_zones = tuple(z.id for z in ctrl.zones if d in zone_days.get(z.id, ()))
            if day_zones:
                sets_to_days.setdefault(day_zones, []).append(d)

        slot_base = (p.id - 1) * n_zones + 1
        for idx, (day_zones, days) in enumerate(sets_to_days.items()):
            if idx >= n_zones:
                _LOGGER.warning(
                    "%s P%s: %s zone/day combinations exceed the %s slots, days %s ignored",
                    c, p.id, len(sets_to_days), n_zones, days,
                )
                continue
            schedule: dict[str, Any] = {
                "name": f"Schedule P{p.id} #{idx + 1}",
                "time": time_value,
                "weekday": list(days),
            }
            if months:
                schedule["month"] = months
            sequences.append({
                "sequence_id": str(slot_base + idx),
                "name": f"P{p.id} {p.name} #{idx + 1}",
                "enabled": prog_enabled,
                "repeat": repeat,
                "delay": str(soak),
                "schedules": [schedule],
                "zones": [
                    {"zone_id": zid, "duration": fmt_duration(zone_secs[zid])}
                    for zid in day_zones
                ],
            })

    out: dict[str, Any] = {
        "name": ctrl.name,
        "controller_id": ctrl.iu_controller_id,
        "enabled": bool(get(eid(c, "system_enabled"))),
        "entity_id": ctrl.entity_id,
        "all_zones_config": {
            "maximum": ctrl.max_zone_duration,
            "allow_manual": True,
            "show": {"timeline": True},
        },
        "zones": [
            {"name": f"Z{z.id} {z.name}", "enabled": True, "entity_id": z.entity_id}
            for z in ctrl.zones
        ],
    }
    if sequences:
        out["sequences"] = sequences
    return out


def build_config(get: Getter, controllers: list[Controller]) -> dict:
    """The mapping under ``irrigation_unlimited:`` (controllers in IU order)."""
    return {"controllers": [build_controller(get, c) for c in controllers]}


def program_sequences(config: dict, ctrl_pos: int, prog: Program) -> list[dict]:
    """Sequences of one program in a built config (name prefix ``P<N> ``)."""
    prefix = f"P{prog.id} "
    return [
        s for s in config["controllers"][ctrl_pos].get("sequences", [])
        if s["name"].startswith(prefix)
    ]


def dump(config: dict) -> str:
    """File text for ``irrigation_unlimited: !include <file>``."""
    return HEADER + yaml.safe_dump(
        config, sort_keys=False, allow_unicode=True, default_flow_style=None, width=120
    )
