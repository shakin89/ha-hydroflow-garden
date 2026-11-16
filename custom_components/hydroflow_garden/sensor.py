"""Sensors: suspension reason, per-zone planned duration and daily usage,
today's rain forecast."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTime
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_WEATHER_ENTITY, SUSPEND_REASONS
from .entity import ManagerEntity, add_grouped
from .iu_config import _num
from .model import Controller, Zone, eid, suspend_reason_key, zone_sensor_object_id
from .planning import parse_seconds
from .runtime import SIGNAL_FORECAST, SIGNAL_USAGE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    rt = entry.runtime_data
    items: list = []
    for sid, ctrl in rt.controllers:
        items.append((sid, SuspendReason(rt, ctrl)))
        for z in ctrl.zones:
            items.append((sid, PlannedSensor(rt, ctrl, z)))
            for days_ago in range(3):
                items.append((sid, UsageSensor(rt, ctrl, z, days_ago)))
    if rt.options.get(CONF_WEATHER_ENTITY):
        items.append((None, ForecastSensor(rt, "mm")))
        items.append((None, ForecastSensor(rt, "prob")))
    add_grouped(async_add_entities, items)


class SuspendReason(ManagerEntity, SensorEntity):
    """Why the controller is suspended: IU's ``suspended`` says that, not why."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SUSPEND_REASONS

    def __init__(self, rt, ctrl: Controller) -> None:
        super().__init__(rt, "sensor", suspend_reason_key(ctrl), "suspend_reason",
                         "mdi:help-circle-outline", ctrl)

    @property
    def native_value(self) -> str:
        value = self.rt.values.get(self._key)
        return value if value in SUSPEND_REASONS else SUSPEND_REASONS[0]

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rt.values.listen(
            lambda *_: self.async_write_ha_state(), self._key))


class _ZoneSensor(ManagerEntity, SensorEntity):
    """``suffix`` (Italian, fixed) only builds the object_id, kept from the
    YAML era; the name comes from ``tkey``."""

    def __init__(self, rt, ctrl: Controller, zone: Zone, suffix: str, tkey: str,
                 icon: str) -> None:
        oid = zone_sensor_object_id(ctrl, zone, suffix)
        super().__init__(rt, "sensor", oid, tkey, icon, ctrl, {"zone": f"Z{zone.id} {zone.name}"})
        self.zone = zone


class UsageSensor(_ZoneSensor):
    """Hours the zone valve was open on a day (replaces history_stats)."""

    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_suggested_display_precision = 2

    # days ago -> (object_id suffix, translation_key)
    DAYS = (("Oggi", "zone_today"), ("Ieri", "zone_yesterday"), ("2gg fa", "zone_two_days_ago"))

    def __init__(self, rt, ctrl, zone, days_ago: int) -> None:
        suffix, tkey = self.DAYS[days_ago]
        super().__init__(rt, ctrl, zone, suffix, tkey, "mdi:timer-sand")
        self.days_ago = days_ago
        if days_ago == 0:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> float:
        return round(self.rt.usage.seconds(self.ctrl, self.zone.id, self.days_ago) / 3600, 4)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_USAGE, self.async_write_ha_state))


class PlannedSensor(_ZoneSensor):
    """Seconds the zone will water next, with the Smart Irrigation details the
    dashboard shows. State: IU's absolute adjustment when set, else the P1
    duration of the zone."""

    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, rt, ctrl, zone) -> None:
        super().__init__(rt, ctrl, zone, "Programmato", "zone_planned", "mdi:sprinkler-variant")

    @property
    def _iu_zone(self) -> str:
        return self.rt.zone_entity(self.ctrl, self.zone.id)

    def _iu_attr(self, name: str, default: Any = None) -> Any:
        st = self.hass.states.get(self._iu_zone)
        value = st.attributes.get(name) if st else None
        return default if value in (None, "") else value

    def _next_prog(self) -> str:
        parts = str(self._iu_attr("next_name", "")).split(" ")
        if len(parts) > 1 and parts[1].lower().startswith("p") and parts[1][1:].isdigit():
            return parts[1].lower()
        return "p1"

    def _cycles(self, pn: str) -> int:
        c = self.ctrl.id
        if not self.rt.get(eid(c, pn, "eco")):
            return 1
        return max(int(_num(self.rt.get(eid(c, pn, "eco_cycles")), 1)), 1)

    @property
    def native_value(self) -> int:
        adj = str(self._iu_attr("adjustment", ""))
        if adj.startswith("="):
            return parse_seconds(adj[1:])
        return int(_num(self.rt.get(eid(self.ctrl.id, "p1", f"z{self.zone.id}_duration")), 0) * 60)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c, pn = self.ctrl.id, self._next_prog()
        attrs: dict[str, Any] = {
            "next_prog": pn,
            "base_minutes": _num(self.rt.get(eid(c, pn, f"z{self.zone.id}_duration")), 0),
            "next_cicli": self._cycles(pn),
            "adjustment": self._iu_attr("adjustment", ""),
            "next_name": self._iu_attr("next_name", "n/a"),
            "next_start": self._iu_attr("next_start", "n/a"),
            "next_duration": self._iu_attr("next_duration", "n/a"),
        }
        si = self.zone.si_sensor
        if si:
            st = self.hass.states.get(si)
            secs = int(_num(st.state if st else 0, 0))
            bucket = abs(_num(st.attributes.get("bucket") if st else 0, 0))
            thr = _num(st.attributes.get("throughput") if st else 0, 0)
            size = _num(st.attributes.get("size") if st else 0, 0)
            nxt = secs // self._cycles(pn)
            attrs.update({
                "si_seconds": secs,
                "si_next_seconds": nxt,
                "si_next_hms": f"{nxt // 60}:{nxt % 60:02d}",
                "bucket_mm": round(bucket, 2),
                "si_calcolato_alle": st.attributes.get("last_calculated") if st else None,
                "size_m2": round(size, 1),
                "throughput_l_min": round(thr, 1),
                "s_per_mm": round(secs / bucket, 1) if bucket > 0 else 0,
                "litri": int(round(secs / 60 * thr)),
                "mm_erogati": round(secs / 60 * thr / size, 2) if size > 0 else 0,
            })
        return attrs

    async def async_added_to_hass(self) -> None:
        tracked = [self._iu_zone] + ([self.zone.si_sensor] if self.zone.si_sensor else [])

        @callback
        def _state(_e: Event[EventStateChangedData]) -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_track_state_change_event(self.hass, tracked, _state))
        prefix = f"iu_{self.ctrl.id}_p"

        @callback
        def _value(key: str, _v: Any) -> None:
            if key.startswith(prefix):
                self.async_write_ha_state()

        self.async_on_remove(self.rt.values.listen(_value))


class ForecastSensor(ManagerEntity, SensorEntity):
    def __init__(self, rt, what: str) -> None:
        if what == "mm":
            super().__init__(rt, "sensor", "precipitazioni_oggi", "rain_today",
                             "mdi:weather-pouring", None)
            self._attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
            self._attr_device_class = SensorDeviceClass.PRECIPITATION
        else:
            super().__init__(rt, "sensor", "probabilita_pioggia_oggi", "rain_probability_today",
                             "mdi:water-percent", None)
            self._attr_native_unit_of_measurement = PERCENTAGE
        self.what = what

    @property
    def native_value(self):
        return self.rt.forecast.get(self.what)

    @property
    def extra_state_attributes(self) -> dict:
        return {"source": f"{self.rt.options.get(CONF_WEATHER_ENTITY)} (get_forecasts daily, forecast[0])"}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_FORECAST, self.async_write_ha_state))
