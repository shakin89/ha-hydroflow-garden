"""Topology (controllers, zones, programs) and the catalogue of value keys.

Pure Python: no Home Assistant import, so the planning code that uses it can be
tested on its own.

Every user-adjustable value of the integration has a *key*, built by ``eid``.
The key is the object_id of its entity (``switch.<key>``, ``number.<key>``...)
and its unique_id. The format is inherited from the YAML generator this
integration replaces, where it was the object_id of the ``input_*`` helpers:
changing it loses the entity registry entries and their history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .const import (
    MONTH_CODES,
    REASON_NONE,
    TIME_FIXED,
    TIME_TYPES,
    WEEKDAY_CODES,
)


def slugify(value: str) -> str:
    """Home Assistant style slug: lowercase, non-alnum -> _, trimmed."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def eid(ctrl: str, *parts: str) -> str:
    """Value key: iu_<ctrl>_<parts...>. NEVER change the format."""
    return "iu_" + "_".join([ctrl, *parts])


@dataclass(frozen=True)
class Zone:
    id: int
    name: str
    entity_id: str
    si_sensor: str = ""  # Smart Irrigation duration sensor, "" = none

    @property
    def smart_irrigation(self) -> bool:
        return bool(self.si_sensor)


@dataclass(frozen=True)
class Program:
    id: int
    name: str
    default_time: str = "06:00"


@dataclass(frozen=True)
class Controller:
    id: str
    name: str
    iu_controller_id: str
    entity_id: str
    max_zone_duration: str = "00:40"
    zones: tuple[Zone, ...] = ()
    programs: tuple[Program, ...] = ()
    fill_switches: tuple[str, ...] = ()
    fill_lead_minutes: int = 120
    fill_duration_minutes: int = 90
    availability_entity: str = ""
    preflight_timeout_minutes: int = 15

    @property
    def has_fill(self) -> bool:
        return bool(self.fill_switches)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Controller:
        return cls(
            id=data["id"],
            name=data["name"],
            iu_controller_id=data.get("iu_controller_id") or slugify(data["name"]),
            entity_id=data.get("entity_id", ""),
            max_zone_duration=data.get("max_zone_duration", "00:40"),
            zones=tuple(
                Zone(
                    id=int(z["id"]),
                    name=z["name"],
                    entity_id=z["entity_id"],
                    si_sensor=z.get("si_sensor") or "",
                )
                for z in sorted(data.get("zones", []), key=lambda z: int(z["id"]))
            ),
            programs=tuple(
                Program(
                    id=int(p["id"]),
                    name=p["name"],
                    default_time=p.get("default_time", "06:00"),
                )
                for p in sorted(data.get("programs", []), key=lambda p: int(p["id"]))
            ),
            fill_switches=tuple(data.get("fill_switches", [])),
            fill_lead_minutes=int(data.get("fill_lead_minutes", 120)),
            fill_duration_minutes=int(data.get("fill_duration_minutes", 90)),
            availability_entity=data.get("availability_entity", "") or "",
            preflight_timeout_minutes=int(data.get("preflight_timeout_minutes", 15)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "iu_controller_id": self.iu_controller_id,
            "entity_id": self.entity_id,
            "max_zone_duration": self.max_zone_duration,
            "zones": [
                {"id": z.id, "name": z.name, "entity_id": z.entity_id, "si_sensor": z.si_sensor}
                for z in self.zones
            ],
            "programs": [
                {"id": p.id, "name": p.name, "default_time": p.default_time}
                for p in self.programs
            ],
            "fill_switches": list(self.fill_switches),
            "fill_lead_minutes": self.fill_lead_minutes,
            "fill_duration_minutes": self.fill_duration_minutes,
            "availability_entity": self.availability_entity,
            "preflight_timeout_minutes": self.preflight_timeout_minutes,
        }


# ---------------------------------------------------------------------------
# Value keys
# ---------------------------------------------------------------------------

KIND_SWITCH = "switch"
KIND_NUMBER = "number"
KIND_TIME = "time"
KIND_SELECT = "select"


@dataclass(frozen=True)
class ValueSpec:
    """One user-adjustable value: becomes one entity.

    ``tkey`` is the entity translation_key: its name (and, for a select, its
    option labels) is in translations/<lang>.json under entity.<platform>,
    with ``placeholders`` such as ``{program}`` filled in."""

    key: str
    kind: str
    tkey: str
    icon: str
    default: Any
    # True when a change must rewrite the IU configuration
    schedule: bool = False
    # number
    min: float = 0
    max: float = 100
    step: float = 1
    unit: str | None = None
    mode: str = "box"
    # select
    options: tuple[str, ...] = ()
    # legacy helper domain the value is seeded from on first start
    legacy_domain: str = ""
    placeholders: dict[str, str] = field(default_factory=dict)


def _sw(key, tkey, icon, default=False, schedule=False, ph=None) -> ValueSpec:
    return ValueSpec(key, KIND_SWITCH, tkey, icon, default, schedule=schedule,
                     legacy_domain="input_boolean", placeholders=ph or {})


def _num(key, tkey, icon, default, mn, mx, step=1, unit=None, schedule=False,
         mode="box", ph=None) -> ValueSpec:
    return ValueSpec(key, KIND_NUMBER, tkey, icon, default, schedule=schedule,
                     min=mn, max=mx, step=step, unit=unit, mode=mode,
                     legacy_domain="input_number", placeholders=ph or {})


def controller_specs(ctrl: Controller) -> list[ValueSpec]:
    """All values of one controller, in a stable order."""
    c = ctrl.id
    specs: list[ValueSpec] = [
        _sw(eid(c, "system_enabled"), "system_enabled", "mdi:water", schedule=True),
        _sw(eid(c, "adjust_rain"), "adjust_rain", "mdi:weather-rainy", True),
        _sw(eid(c, "logging"), "logging", "mdi:file-document-outline", True),
        _sw(eid(c, "notifications"), "notifications", "mdi:bell-outline", True),
        _num(eid(c, "test_duration"), "test_duration", "mdi:timer-outline", 30, 5, 300, 5, "s"),
    ]
    if ctrl.availability_entity:
        specs += [
            _sw(eid(c, "preflight"), "preflight", "mdi:lan-check", True),
            _num(eid(c, "preflight_timeout_minutes"), "preflight_timeout",
                 "mdi:timer-alert-outline", ctrl.preflight_timeout_minutes, 1, 60, 1, "min"),
        ]
    if ctrl.has_fill:
        specs += [
            _num(eid(c, "fill_lead_minutes"), "fill_lead", "mdi:water-pump",
                 ctrl.fill_lead_minutes, 0, 240, 5, "min"),
            _num(eid(c, "fill_duration_minutes"), "fill_duration", "mdi:clock-end",
                 ctrl.fill_duration_minutes, 0, 240, 5, "min"),
        ]
    for p in ctrl.programs:
        pn = f"p{p.id}"
        ph = {"program": f"P{p.id} {p.name}"}
        specs += [
            _sw(eid(c, pn, "enabled"), "program_enabled", "mdi:calendar-check", schedule=True, ph=ph),
            ValueSpec(eid(c, pn, "time_type"), KIND_SELECT, "time_type",
                      "mdi:clock-outline", TIME_FIXED, schedule=True,
                      options=tuple(TIME_TYPES), legacy_domain="input_select", placeholders=ph),
            ValueSpec(eid(c, pn, "time"), KIND_TIME, "program_time", "mdi:clock",
                      p.default_time if len(p.default_time) > 5 else p.default_time + ":00",
                      schedule=True, legacy_domain="input_datetime", placeholders=ph),
            _num(eid(c, pn, "offset"), "program_offset", "mdi:delta", 0, -120, 120, 1,
                 "min", schedule=True, ph=ph),
            _sw(eid(c, pn, "eco"), "program_eco", "mdi:leaf", schedule=True, ph=ph),
            _num(eid(c, pn, "eco_cycles"), "program_eco_cycles", "mdi:repeat", 2, 1, 5, 1,
                 schedule=True, ph=ph),
            # Seconds (may be negative: IU overlaps the cycles). The YAML
            # helper said "min" but its value was always used as seconds.
            _num(eid(c, pn, "eco_soak"), "program_eco_soak", "mdi:timer-sand", 600,
                 -600, 3600, 1, "s", schedule=True, ph=ph),
        ]
        for code in MONTH_CODES:
            specs.append(_sw(eid(c, pn, code), f"program_month_{code}", "mdi:calendar-month",
                             code in ("apr", "may", "jun", "jul", "aug", "sep"), True, ph))
        for z in ctrl.zones:
            zph = {**ph, "zone": f"Z{z.id} {z.name}"}
            specs.append(_sw(eid(c, pn, f"z{z.id}_enabled"), "zone_enabled",
                             "mdi:sprinkler-variant", p.id == 1, True, zph))
            specs.append(_num(eid(c, pn, f"z{z.id}_duration"), "zone_duration",
                              "mdi:timer-outline", 10, 0, 60, 1, "min", schedule=True,
                              mode="slider", ph=zph))
            for code in WEEKDAY_CODES:
                specs.append(_sw(eid(c, pn, f"z{z.id}_{code}"), f"zone_day_{code}",
                                 "mdi:calendar", code in ("mon", "wed", "fri"), True, zph))
    return specs


def zone_sensor_object_id(ctrl: Controller, zone: Zone, suffix: str) -> str:
    """object_id of the per-zone sensors (derived from the name, as before)."""
    return slugify(f"IU {ctrl.name} Z{zone.id} {zone.name} {suffix}")


def suspend_reason_key(ctrl: Controller) -> str:
    return eid(ctrl.id, "suspend_reason")


__all__ = [
    "Controller",
    "Program",
    "Zone",
    "ValueSpec",
    "controller_specs",
    "eid",
    "slugify",
    "MONTH_CODES",
    "REASON_NONE",
]
