"""What Irrigation Unlimited must run, and how it gets there without files.

Pure Python (only PyYAML, which Home Assistant ships).

* ``build_config`` / ``build_controller``: the *effective* configuration, the
  one IU must end up running. Ported from ``_build_iu_context`` of the YAML
  generator; pinned by tests/test_iu_config_parity.py.
* ``build_structure``: the *static* YAML the user pastes once into their own
  IU file. Every program owns up to 7 sequences (slots, one per distinct set
  of zones), each with every zone and one schedule, disabled. It changes only with the topology and eco.
* ``sync_calls``: the IU service calls that turn the structure into the
  effective configuration at runtime (``load_schedule``, ``enable`` /
  ``disable`` of sequence zones, ``adjust_time`` of sequence zones). The
  integration never writes the IU file.

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

import hashlib
import json
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
from .model import Controller, Program, eid, slugify

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


# --- static structure ------------------------------------------------------
STRUCTURE_ATTR = "user_hydroflow_structure"  # IU exposes user: keys as user_<key>
_PLACEHOLDER_DURATION = "00:01:00"  # always replaced by adjust_time


def slot_id(ctrl: Controller, prog: Program, idx: int) -> str:
    """``sequence_id`` of slot ``idx`` (0-based) of ``prog``."""
    return str((prog.id - 1) * len(ctrl.zones) + idx + 1)


def slots_per_program(ctrl: Controller) -> int:
    """Slots a program can use: one per distinct set of zones, and every
    weekday is in one set only, so never more than 7."""
    return min(len(WEEKDAY_CODES), len(ctrl.zones))


def schedule_id(ctrl: Controller, slot: str) -> str:
    """Unique over every controller: load_schedule takes the first match."""
    return f"hf_{slugify(ctrl.id)}_s{slot}"


def _eco(get: Getter, ctrl: Controller, prog: Program) -> tuple[int, int]:
    """(repeat, soak seconds) of the program's sequences."""
    pn = f"p{prog.id}"
    if not get(eid(ctrl.id, pn, "eco")):
        return 1, 0
    cycles = int(_num(get(eid(ctrl.id, pn, "eco_cycles")), 2))
    return max(cycles, 1), int(_num(get(eid(ctrl.id, pn, "eco_soak")), 600))


def _structure_body(get: Getter, ctrl: Controller) -> dict:
    sequences: list[dict] = []
    for p in ctrl.programs:
        repeat, soak = _eco(get, ctrl, p)
        for idx in range(slots_per_program(ctrl)):
            slot = slot_id(ctrl, p, idx)
            sequences.append({
                "sequence_id": slot,
                "name": f"P{p.id} {p.name} #{idx + 1}",
                "repeat": repeat,
                "delay": str(soak),
                # disabled until the integration loads it, so that nothing
                # runs on what the file says
                "schedules": [{
                    "schedule_id": schedule_id(ctrl, slot),
                    "name": f"Schedule P{p.id} #{idx + 1}",
                    "time": "00:00",
                    "enabled": False,
                }],
                "zones": [{"zone_id": z.id, "duration": _PLACEHOLDER_DURATION} for z in ctrl.zones],
            })
    out: dict[str, Any] = {
        "name": ctrl.name,
        "controller_id": ctrl.iu_controller_id,
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


def structure_digest(get: Getter, ctrl: Controller) -> str:
    body = _structure_body(get, ctrl)
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def build_structure(get: Getter, controllers: list[Controller]) -> dict:
    """The mapping under ``irrigation_unlimited:`` the user pastes. Each
    controller carries its digest (``user:``), read back from the IU master
    entity to know whether the file in use is the current one."""
    out = []
    for c in controllers:
        body = _structure_body(get, c)
        body["user"] = {STRUCTURE_ATTR.removeprefix("user_"): structure_digest(get, c)}
        out.append(body)
    return {"controllers": out}


# --- runtime sync -------------------------------------------------------------
SyncCalls = dict[tuple, tuple[str, dict]]


def sync_calls(get: Getter, ctrl: Controller,
               overrides: dict[tuple[int, int], int] | None = None) -> SyncCalls:
    """{key: (IU service, data without entity_id)} bringing a controller that
    runs ``build_structure`` to ``build_controller``. Keys are stable, so a
    caller can send only what changed since the last push.

    ``overrides``: seconds per cycle by (program id, zone id), set by Smart
    Irrigation, replacing the programmed duration of the zone."""
    overrides = overrides or {}
    eff = {s["sequence_id"]: s for s in build_controller(get, ctrl).get("sequences", [])}
    index = {z.id: k + 1 for k, z in enumerate(ctrl.zones)}  # 1-based sequence zone
    calls: SyncCalls = {
        ("controller",): ("enable" if get(eid(ctrl.id, "system_enabled")) else "disable", {}),
        # Durations live on the sequence zones. Up to 0.4.0-beta.2 Smart
        # Irrigation adjusted the zones themselves, and IU restores that.
        ("zone_adjustments",): ("adjust_time", {"reset": None}),
    }
    for p in ctrl.programs:
        for idx in range(slots_per_program(ctrl)):
            slot = slot_id(ctrl, p, idx)
            sid = schedule_id(ctrl, slot)
            seq = eff.get(slot)
            if seq is None:
                calls[("schedule", slot)] = ("load_schedule", {"schedule_id": sid, "enabled": False})
                continue
            sch = seq["schedules"][0]
            calls[("schedule", slot)] = ("load_schedule", {
                "schedule_id": sid,
                "time": sch["time"],
                "weekday": list(sch["weekday"]),
                "month": list(sch.get("month") or MONTH_CODES),
                "enabled": bool(seq["enabled"]),
            })
            used = {zr["zone_id"]: zr["duration"] for zr in seq["zones"]}
            on = [index[z] for z in used]
            off = [index[z.id] for z in ctrl.zones if z.id not in used]
            calls[("zones_on", slot)] = ("enable", {"sequence_id": [slot], "zones": on})
            if off:
                calls[("zones_off", slot)] = ("disable", {"sequence_id": [slot], "zones": off})
            for zid, duration in used.items():
                if (p.id, zid) in overrides:
                    duration = fmt_duration(overrides[(p.id, zid)])
                calls[("duration", slot, zid)] = ("adjust_time", {
                    "sequence_id": [slot], "zones": [index[zid]], "actual": duration,
                })
    return calls


def program_sequences(config: dict, ctrl_pos: int, prog: Program) -> list[dict]:
    """Sequences of one program in a built config (name prefix ``P<N> ``)."""
    prefix = f"P{prog.id} "
    return [
        s for s in config["controllers"][ctrl_pos].get("sequences", [])
        if s["name"].startswith(prefix)
    ]


class _NoAliasDumper(yaml.SafeDumper):
    """Write shared lists in full instead of ``&id001`` anchors."""

    def ignore_aliases(self, data) -> bool:
        return True


def dump(config: dict) -> str:
    """YAML text of a configuration, with the header comment."""
    return HEADER + yaml.dump(
        config, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True,
        default_flow_style=None, width=120,
    )
