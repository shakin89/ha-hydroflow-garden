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
    MONTHS,
    REASON_NONE,
    STATUS_TABS,
    TIME_FIXED,
    TIME_TYPES,
    WEEKDAYS,
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
    """One user-adjustable value: becomes one entity."""

    key: str
    kind: str
    name: str
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
    extra: dict = field(default_factory=dict)


def _sw(key, name, icon, default=False, schedule=False) -> ValueSpec:
    return ValueSpec(key, KIND_SWITCH, name, icon, default, schedule=schedule,
                     legacy_domain="input_boolean")


def _num(key, name, icon, default, mn, mx, step=1, unit=None, schedule=False,
         mode="box") -> ValueSpec:
    return ValueSpec(key, KIND_NUMBER, name, icon, default, schedule=schedule,
                     min=mn, max=mx, step=step, unit=unit, mode=mode,
                     legacy_domain="input_number")


def controller_specs(ctrl: Controller) -> list[ValueSpec]:
    """All values of one controller, in a stable order."""
    c = ctrl.id
    specs: list[ValueSpec] = [
        _sw(eid(c, "system_enabled"), "Sistema attivo", "mdi:water", schedule=True),
        _sw(eid(c, "adjust_rain"), "Annulla se piove", "mdi:weather-rainy", True),
        _sw(eid(c, "logging"), "Log attivo", "mdi:file-document-outline", True),
        _sw(eid(c, "notifications"), "Notifiche", "mdi:bell-outline", True),
        _num(eid(c, "test_duration"), "Durata test", "mdi:timer-outline", 30, 5, 300, 5, "s"),
        ValueSpec(eid(c, "status_tab"), KIND_SELECT, "Tab stato", "mdi:tab",
                  STATUS_TABS[0], options=tuple(STATUS_TABS), legacy_domain="input_select"),
    ]
    if ctrl.availability_entity:
        specs += [
            _sw(eid(c, "preflight"), "Preflight device", "mdi:lan-check", True),
            _num(eid(c, "preflight_timeout_minutes"), "Timeout preflight",
                 "mdi:timer-alert-outline", ctrl.preflight_timeout_minutes, 1, 60, 1, "min"),
        ]
    if ctrl.has_fill:
        specs += [
            _num(eid(c, "fill_lead_minutes"), "Anticipo riempimento", "mdi:water-pump",
                 ctrl.fill_lead_minutes, 0, 240, 5, "min"),
            _num(eid(c, "fill_duration_minutes"), "Durata riempimento", "mdi:clock-end",
                 ctrl.fill_duration_minutes, 0, 240, 5, "min"),
        ]
    for p in ctrl.programs:
        pn = f"p{p.id}"
        lbl = f"P{p.id} {p.name}"
        specs += [
            _sw(eid(c, pn, "enabled"), f"{lbl} attivo", "mdi:calendar-check", schedule=True),
            ValueSpec(eid(c, pn, "time_type"), KIND_SELECT, f"{lbl} tipo orario",
                      "mdi:clock-outline", TIME_FIXED, schedule=True,
                      options=tuple(TIME_TYPES), legacy_domain="input_select"),
            ValueSpec(eid(c, pn, "time"), KIND_TIME, f"{lbl} orario", "mdi:clock",
                      p.default_time if len(p.default_time) > 5 else p.default_time + ":00",
                      schedule=True, legacy_domain="input_datetime"),
            _num(eid(c, pn, "offset"), f"{lbl} offset sole", "mdi:delta", 0, -120, 120, 1,
                 "min", schedule=True),
            _sw(eid(c, pn, "eco"), f"{lbl} eco", "mdi:leaf", schedule=True),
            _num(eid(c, pn, "eco_cycles"), f"{lbl} eco cicli", "mdi:repeat", 2, 1, 5, 1,
                 schedule=True),
            # Seconds (may be negative: IU overlaps the cycles). The YAML
            # helper said "min" but its value was always used as seconds.
            _num(eid(c, pn, "eco_soak"), f"{lbl} pausa eco", "mdi:timer-sand", 600,
                 -600, 3600, 1, "s", schedule=True),
        ]
        for code, mname, _ in MONTHS:
            specs.append(_sw(eid(c, pn, code), f"{lbl} {mname}", "mdi:calendar-month",
                             code in ("apr", "may", "jun", "jul", "aug", "sep"), True))
        for z in ctrl.zones:
            zl = f"{lbl} Z{z.id} {z.name}"
            specs.append(_sw(eid(c, pn, f"z{z.id}_enabled"), zl, "mdi:sprinkler-variant",
                             p.id == 1, True))
            specs.append(_num(eid(c, pn, f"z{z.id}_duration"), f"{zl} durata",
                              "mdi:timer-outline", 10, 0, 60, 1, "min", schedule=True,
                              mode="slider"))
            for code, dname, _ in WEEKDAYS:
                specs.append(_sw(eid(c, pn, f"z{z.id}_{code}"), f"{zl} {dname}",
                                 "mdi:calendar", code in ("mon", "wed", "fri"), True))
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
