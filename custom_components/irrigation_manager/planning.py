"""Pure decisions of the engine: what to adjust, how long to suspend, when to
reset a bucket. No Home Assistant import."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import PREFLIGHT_SUSPEND_MARGIN, SI_RESET_RATIO, WEEKDAY_CODES
from .iu_config import Getter, _num, build_controller, program_repeat
from .model import Controller, Program, Zone, eid


def suspend_seconds(get: Getter, ctrl: Controller, prog: Program, start: datetime) -> int:
    """Length of the run of ``prog`` starting at ``start``, plus a margin.

    Sum of the durations of the zones enabled on the run's weekday. Eco does
    not change the water total (durations are split over the cycles); the
    soak between cycles is the only additive term.
    """
    c, pn = ctrl.id, f"p{prog.id}"
    day = WEEKDAY_CODES[start.weekday()]
    total = 0
    for z in ctrl.zones:
        if get(eid(c, pn, f"z{z.id}_enabled")) and get(eid(c, pn, f"z{z.id}_{day}")):
            total += int(_num(get(eid(c, pn, f"z{z.id}_duration")), 10)) * 60
    if get(eid(c, pn, "eco")):
        cycles = int(_num(get(eid(c, pn, "eco_cycles")), 2))
        total += int(_num(get(eid(c, pn, "eco_soak")), 600)) * cycles
    return total + PREFLIGHT_SUSPEND_MARGIN


def si_zones_of_program(get: Getter, ctrl: Controller, prog: Program) -> list[Zone]:
    """Zones with a Smart Irrigation sensor that some sequence of the program
    waters, each once (IU adjusts at zone level)."""
    built = build_controller(get, ctrl)
    prefix = f"P{prog.id} "
    ids: list[int] = []
    for seq in built.get("sequences", []):
        if not seq["name"].startswith(prefix):
            continue
        for zr in seq["zones"]:
            if zr["zone_id"] not in ids:
                ids.append(zr["zone_id"])
    by_id = {z.id: z for z in ctrl.zones}
    return [by_id[i] for i in ids if by_id[i].smart_irrigation]


def parse_seconds(value: Any) -> int:
    """Seconds from a number or an ``[H:]MM:SS`` string; 0 when unusable."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if ":" in text:
        try:
            parts = [float(p) for p in text.split(":")]
        except ValueError:
            return 0
        secs = 0.0
        for p in parts:
            secs = secs * 60 + p
        return int(secs)
    try:
        return int(float(text))
    except ValueError:
        return 0


def si_adjust_seconds(si_state: Any, repeat: int) -> int:
    """Seconds per cycle IU should water: the SI duration split over cycles."""
    try:
        secs = int(float(si_state))
    except (TypeError, ValueError):
        secs = 0
    return max(secs, 0) // max(repeat, 1)


def zones_to_reset(
    ctrl: Controller,
    start_zones: list[dict],
    finish_zones: list[dict],
    device_online: bool,
) -> list[Zone]:
    """SI zones whose bucket may be reset after a finished sequence.

    Only zones planned > 0 that delivered >= 90% of it, and only when the
    valve device was online: planned and actual both come from IU's timer,
    which keeps counting with the device offline.
    """
    if not device_online:
        return []

    def by_zone(zones: list[dict]) -> dict[int, int]:
        out: dict[int, int] = {}
        for z in zones or []:
            try:
                out[int(z.get("zone_id"))] = parse_seconds(z.get("duration"))
            except (TypeError, ValueError):
                continue
        return out

    planned, actual = by_zone(start_zones), by_zone(finish_zones)
    return [
        z for z in ctrl.zones
        if z.smart_irrigation
        and planned.get(z.id, 0) > 0
        and actual.get(z.id, 0) >= planned[z.id] * SI_RESET_RATIO
    ]


__all__ = ["program_repeat", "si_adjust_seconds", "si_zones_of_program",
           "suspend_seconds", "zones_to_reset"]
