"""The behaviours the YAML generator emitted as automations, in Python.

Timed actions (fill, preflight, Smart Irrigation adjust) are anchored on the
next start IU itself reports in the ``sequence_status`` of each controller,
so they follow exactly the schedule IU runs (weekdays, months, sun times,
suspensions) without re-implementing it.

Event actions react to IU's sequence-level events. ``data.zone`` (singular)
exists only on valve_on/valve_off; start/finish carry ``data.zones``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_OFF
from homeassistant.core import (
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MM_THRESHOLD,
    CONF_PROB_THRESHOLD,
    CONF_SKIP_HOURS,
    CONF_SKIP_TIME,
    CONF_WEATHER_ENTITY,
    EVENT_IU_CANCEL,
    EVENT_IU_FINISH,
    EVENT_IU_START,
    EVENT_IU_VALVE_OFF,
    EVENT_IU_VALVE_ON,
    IU_DOMAIN,
    REASON_OFFLINE,
    REASON_RAIN,
    SI_ADJUST_LEAD_DEFAULT,
    SI_ADJUST_LEAD_KEY,
    SI_DOMAIN,
)
from .iu_config import _num, fmt_duration, program_repeat
from .logfile import format_line
from .model import Controller, Program, eid
from .notify import async_notify
from .planning import (
    si_adjust_seconds,
    si_zones_of_program,
    suspend_seconds,
    zones_to_reset,
)
from .runtime import SIGNAL_SI_OVERRIDE, async_get_today_forecast

if TYPE_CHECKING:
    from .runtime import IrrigationRuntime

_LOGGER = logging.getLogger(__name__)

KIND_FILL = "fill"
KIND_PREFLIGHT = "preflight"
KIND_SI = "si_adjust"


def _parse_start(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    if isinstance(value, str) and value:
        parsed = dt_util.parse_datetime(value)
        return dt_util.as_local(parsed) if parsed else None
    return None


def _no_zone(data: dict) -> bool:
    return data.get("zone") is None


class Engine:
    def __init__(self, rt: IrrigationRuntime) -> None:
        self.rt = rt
        self.hass: HomeAssistant = rt.hass
        self._unsubs: list[Callable[[], None]] = []
        # (ctrl id, program id, kind) -> (fire time, cancel)
        self._timers: dict[tuple[str, int, str], tuple[datetime, Callable[[], None]]] = {}
        # occurrences already handled: (ctrl, prog, kind, start iso)
        self._done: set[tuple[str, int, str, str]] = set()
        # IU sequence entity -> (controller, start zones, started at)
        self._si_pending: dict[str, tuple[Controller, list[dict], datetime]] = {}
        self._tasks: set[asyncio.Task] = set()

    # --- helpers -----------------------------------------------------------
    def _on(self, key: str) -> bool:
        return bool(self.rt.get(key))

    def _minutes(self, key: str, default: int) -> int:
        return int(_num(self.rt.get(key), default))

    def _spawn(self, coro, background: bool = False) -> None:
        """Track the task so a reload cancels it. Long waits (preflight) run
        as background tasks: nothing should wait for them to finish."""
        if background:
            task = self.hass.async_create_background_task(coro, f"{__name__}.wait")
        else:
            task = self.hass.async_create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _log(self, ctrl: Controller, line: str) -> None:
        if self._on(eid(ctrl.id, "logging")):
            await self.rt.log.async_write(line)

    async def _notify(self, ctrl: Controller | None, message: str, gated: bool = True) -> None:
        """``gated``: honour the controller's notifications switch. Hardware
        faults (device offline) and skip decisions are never gated."""
        if gated and ctrl is not None and not self._on(eid(ctrl.id, "notifications")):
            return
        await async_notify(self.hass, self.rt.options, self.rt.texts("notify.title"), message)

    async def _call(self, domain: str, service: str, data: dict, **kw) -> bool:
        if not self.hass.services.has_service(domain, service):
            _LOGGER.warning("Service %s.%s not available", domain, service)
            return False
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True, **kw)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("%s.%s failed: %s", domain, service, err)
            return False
        return True

    def _controller_active(self, ctrl: Controller) -> bool:
        return self._on(eid(ctrl.id, "system_enabled")) and any(
            self._on(eid(ctrl.id, f"p{p.id}", "enabled")) for p in ctrl.programs
        )

    # --- lifecycle ----------------------------------------------------------
    async def async_start(self) -> None:
        hass = self.hass
        for event in (EVENT_IU_START, EVENT_IU_FINISH, EVENT_IU_CANCEL,
                      EVENT_IU_VALVE_ON, EVENT_IU_VALVE_OFF):
            self._unsubs.append(hass.bus.async_listen(event, self._on_iu_event))

        masters = [self.rt.master(c) for c in self.rt.controller_list]
        if masters:
            self._unsubs.append(async_track_state_change_event(hass, masters, self._replan_cb))
        self._unsubs.append(self.rt.values.listen(self._on_value))
        self._unsubs.append(async_track_time_interval(hass, self._replan_cb, timedelta(minutes=15)))

        skip = dt_util.parse_time(str(self.rt.options.get(CONF_SKIP_TIME, "02:00:00")))
        if skip and self.rt.options.get(CONF_WEATHER_ENTITY):
            self._unsubs.append(async_track_time_change(
                hass, self._rain_skip_cb, skip.hour, skip.minute, skip.second))
        if any(z.smart_irrigation for c in self.rt.controller_list for z in c.zones):
            self._unsubs.append(async_track_time_change(
                hass, self._si_hourly_cb, minute=10, second=0))

        from .runtime import SIGNAL_RAIN_NOW
        self._unsubs.append(async_dispatcher_connect(hass, SIGNAL_RAIN_NOW, self._rain_now_cb))

        if hass.state is CoreState.running:
            self._replan()
        else:
            self._unsubs.append(hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._ha_started))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for _, cancel in self._timers.values():
            cancel()
        self._timers.clear()
        for task in list(self._tasks):
            task.cancel()

    async def _ha_started(self, _event: Event) -> None:
        self._replan()
        for ctrl in self.rt.controller_list:
            await self._log(ctrl, format_line("HA RESTART", ctrl.name, zone="none", duration=None))

    # --- planning of timed actions -----------------------------------------
    @callback
    def _replan_cb(self, *_args) -> None:
        self._replan()

    @callback
    def _on_value(self, key: str, _value: Any) -> None:
        if key == SI_ADJUST_LEAD_KEY or key.endswith(("_lead_minutes", "_timeout_minutes")):
            self._replan()

    def next_starts(self, ctrl: Controller) -> dict[int, datetime]:
        """Next start per program, from IU's sequence_status (name ``P<N> ...``)."""
        state = self.hass.states.get(self.rt.master(ctrl))
        if state is None:
            return {}
        out: dict[int, datetime] = {}
        for seq in state.attributes.get("sequence_status") or []:
            name = str(seq.get("name") or "")
            start = _parse_start(seq.get("start"))
            if start is None or not name.startswith("P"):
                continue
            try:
                pid = int(name.split()[0][1:])
            except ValueError:
                continue
            if pid not in out or start < out[pid]:
                out[pid] = start
        return out

    def _leads(self, ctrl: Controller) -> dict[str, int]:
        c = ctrl.id
        leads: dict[str, int] = {}
        if ctrl.has_fill:
            leads[KIND_FILL] = self._minutes(eid(c, "fill_lead_minutes"), ctrl.fill_lead_minutes)
        if ctrl.availability_entity:
            leads[KIND_PREFLIGHT] = self._minutes(
                eid(c, "preflight_timeout_minutes"), ctrl.preflight_timeout_minutes)
        if any(z.smart_irrigation for z in ctrl.zones):
            leads[KIND_SI] = self._minutes(SI_ADJUST_LEAD_KEY, SI_ADJUST_LEAD_DEFAULT)
        return leads

    @callback
    def _replan(self) -> None:
        now = dt_util.now()
        wanted: dict[tuple[str, int, str], tuple[datetime, datetime]] = {}
        for ctrl in self.rt.controller_list:
            starts = self.next_starts(ctrl)
            for kind, lead in self._leads(ctrl).items():
                if lead <= 0:
                    continue
                for pid, start in starts.items():
                    fire = start - timedelta(minutes=lead)
                    if fire > now:
                        wanted[(ctrl.id, pid, kind)] = (fire, start)
        for key in list(self._timers):
            if key not in wanted or wanted[key][0] != self._timers[key][0]:
                self._timers.pop(key)[1]()
        for key, (fire, start) in wanted.items():
            if key in self._timers:
                continue
            ctrl_id, pid, kind = key
            self._timers[key] = (fire, async_track_point_in_time(
                self.hass, self._make_fire(ctrl_id, pid, kind, start), fire))

    def _make_fire(self, ctrl_id: str, pid: int, kind: str, start: datetime):
        @callback
        def _fire(_now: datetime) -> None:
            self._timers.pop((ctrl_id, pid, kind), None)
            done = (ctrl_id, pid, kind, start.isoformat())
            if done in self._done:
                return
            self._done.add(done)
            ctrl = next((c for c in self.rt.controller_list if c.id == ctrl_id), None)
            prog = next((p for p in ctrl.programs if p.id == pid), None) if ctrl else None
            if ctrl is None or prog is None:
                return
            handler = {KIND_FILL: self._fill, KIND_PREFLIGHT: self._preflight,
                       KIND_SI: self._si_adjust}[kind]
            self._spawn(handler(ctrl, prog, start), background=kind == KIND_PREFLIGHT)
        return _fire

    # --- fill ---------------------------------------------------------------
    async def _fill(self, ctrl: Controller, prog: Program, start: datetime) -> None:
        first = self.hass.states.get(ctrl.fill_switches[0])
        if first is not None and first.state != STATE_OFF:
            return  # already filling (programs close together)
        if not self.rt.is_online(ctrl):
            await self._notify(ctrl, self.rt.texts(
                "notify.fill_offline", ctrl=ctrl.name, prog=prog.id, device=ctrl.availability_entity,
            ), gated=False)
            return
        if self.rt.fill_minutes(ctrl) <= 0:
            return
        # The runtime turns it off after the fill duration (rt._watch_fill).
        await self._call("homeassistant", "turn_on", {"entity_id": list(ctrl.fill_switches)})

    # --- preflight ----------------------------------------------------------
    async def _preflight(self, ctrl: Controller, prog: Program, start: datetime) -> None:
        if not self._on(eid(ctrl.id, "preflight")):
            return
        master = self.rt.master(ctrl)
        mstate = self.hass.states.get(master)
        if mstate is not None and mstate.attributes.get("suspended") is not None:
            return  # already suspended (e.g. rain): nothing to save, no noise
        if self.rt.is_online(ctrl):
            return
        timeout = self._minutes(eid(ctrl.id, "preflight_timeout_minutes"),
                                ctrl.preflight_timeout_minutes)
        # One minute shorter than the lead, so the suspend lands before IU starts.
        wait = max(timeout - 1, 1) * 60
        done = asyncio.Event()

        @callback
        def _changed(_e: Event[EventStateChangedData]) -> None:
            if self.rt.is_online(ctrl):
                done.set()

        @callback
        def _timeout(_now: datetime) -> None:
            done.set()

        unsubs = [
            async_track_state_change_event(self.hass, [ctrl.availability_entity], _changed),
            async_call_later(self.hass, wait, _timeout),
        ]
        try:
            await done.wait()
        finally:
            for unsub in unsubs:
                unsub()
        if self.rt.is_online(ctrl):
            return  # device back in time: the run goes ahead

        secs = suspend_seconds(self.rt.get, ctrl, prog, start)
        self.rt.set_reason(ctrl, REASON_OFFLINE)
        await self._call(IU_DOMAIN, "suspend", {"entity_id": master, "for": fmt_duration(secs)})
        await self._notify(ctrl, self.rt.texts(
            "notify.preflight_suspended", ctrl=ctrl.name, prog=prog.id, name=prog.name,
            device=ctrl.availability_entity, minutes=timeout,
        ), gated=False)
        await self._log(ctrl, format_line("preflight_fail", ctrl.name, sequence=f"P{prog.id} {prog.name}",
                                          duration=secs))

    # --- Smart Irrigation ---------------------------------------------------
    async def _si_adjust(self, ctrl: Controller, prog: Program, start: datetime) -> None:
        zones = si_zones_of_program(self.rt.get, ctrl, prog)
        if not zones:
            return
        await self._call(SI_DOMAIN, "update_weather", {})
        await self._call(SI_DOMAIN, "calculate", {})
        repeat = program_repeat(self.rt.get, ctrl, prog)
        # On the sequence zones of the program, like every duration: IU
        # ignores a zone-level adjustment in a sequence that has its own.
        overrides = self.rt.si_override.setdefault(ctrl.id, {})
        for z in zones:
            st = self.hass.states.get(z.si_sensor)
            overrides[(prog.id, z.id)] = si_adjust_seconds(st.state if st else None, repeat)
        async_dispatcher_send(self.hass, SIGNAL_SI_OVERRIDE)
        await self.rt.async_sync_iu()

    @callback
    def _si_hourly_cb(self, _now: datetime) -> None:
        """Keep the SI buckets (and the dashboard estimate) fresh during the
        day; skipped while a controller waters, not to race adjust or reset."""
        for ctrl in self.rt.controller_list:
            st = self.hass.states.get(self.rt.master(ctrl))
            if st is not None and st.state != STATE_OFF:
                return
        self._spawn(self._call(SI_DOMAIN, "calculate", {}))

    # --- rain ---------------------------------------------------------------
    @callback
    def _rain_skip_cb(self, _now: datetime) -> None:
        self._spawn(self.async_rain_skip())

    async def async_rain_skip(self, force: bool = False) -> bool:
        """Suspend the active controllers when today's forecast says rain
        (probability AND millimetres over their thresholds)."""
        active = [c for c in self.rt.controller_list if self._controller_active(c)]
        if not active:
            return False
        fc = await async_get_today_forecast(self.hass, self.rt.options.get(CONF_WEATHER_ENTITY))
        if fc is None:
            return False
        prob_t = int(self.rt.options.get(CONF_PROB_THRESHOLD, 70))
        mm_t = float(self.rt.options.get(CONF_MM_THRESHOLD, 3.0))
        if not force and not (fc["prob"] >= prob_t and fc["mm"] >= mm_t):
            return False
        hours = int(self.rt.options.get(CONF_SKIP_HOURS, 22))
        for ctrl in active:
            self.rt.set_reason(ctrl, REASON_RAIN)
            await self._call(IU_DOMAIN, "suspend",
                             {"entity_id": self.rt.master(ctrl), "for": f"{hours:02d}:00:00"})
        names = ", ".join(c.name for c in active)
        await self._notify(None, self.rt.texts(
            "notify.rain_skip", prob=fc["prob"], mm=fc["mm"], prob_t=prob_t, mm_t=mm_t,
            hours=hours, names=names,
        ), gated=False)
        return True

    @callback
    def _rain_now_cb(self) -> None:
        if not self.rt.rain_now():
            return
        for ctrl in self.rt.controller_list:
            if self._on(eid(ctrl.id, "adjust_rain")) and self._controller_active(ctrl):
                self._spawn(self._notify(ctrl, self.rt.texts("notify.rain_detected", ctrl=ctrl.name)))

    # --- IU events -----------------------------------------------------------
    @callback
    def _on_iu_event(self, event: Event) -> None:
        data = event.data
        ctrl = self.rt.controller_by_index((data.get("controller") or {}).get("index"))
        if ctrl is None:
            return
        handler = {
            EVENT_IU_START: self._on_start,
            EVENT_IU_FINISH: self._on_finish,
            EVENT_IU_CANCEL: self._on_cancel,
            EVENT_IU_VALVE_ON: self._on_valve,
            EVENT_IU_VALVE_OFF: self._on_valve,
        }[event.event_type]
        self._spawn(handler(ctrl, data, event.event_type))

    async def _on_start(self, ctrl: Controller, data: dict, _etype: str) -> None:
        master = self.rt.master(ctrl)
        seq_name = (data.get("sequence") or {}).get("name", "")
        scheduled = (data.get("schedule") or {}).get("index") is not None

        # Rain now: cancel scheduled runs (manual runs are the user's choice).
        if scheduled and self._on(eid(ctrl.id, "adjust_rain")) and self.rt.rain_now():
            await self._call(IU_DOMAIN, "cancel", {"entity_id": master})
            return
        # Device offline at start: cancel any run, manual included (nothing
        # would get wet, and IU would still report the full duration).
        if ctrl.availability_entity and self._on(eid(ctrl.id, "preflight")) \
                and not self.rt.is_online(ctrl):
            await self._call(IU_DOMAIN, "cancel", {"entity_id": master})
            await self._notify(ctrl, self.rt.texts(
                "notify.start_offline", ctrl=ctrl.name, device=ctrl.availability_entity,
            ), gated=False)
            await self._log(ctrl, format_line("preflight_cancel", ctrl.name, sequence=seq_name))
            return

        if any(z.smart_irrigation for z in ctrl.zones) and data.get("entity_id"):
            self._si_pending[data["entity_id"]] = (ctrl, list(data.get("zones") or []), dt_util.now())
        if _no_zone(data):
            duration = int(_num((data.get("run") or {}).get("duration"), 0))
            await self._log(ctrl, format_line("ctrl_start", ctrl.name, sequence=seq_name, duration=duration))
            await self._notify(ctrl, self.rt.texts(
                "notify.run_start", ctrl=ctrl.name, seq=seq_name, minutes=round(duration / 60)))

    async def _on_finish(self, ctrl: Controller, data: dict, _etype: str) -> None:
        seq_name = (data.get("sequence") or {}).get("name", "")
        pending = self._si_pending.pop(data.get("entity_id", ""), None)
        if pending is not None:
            _, start_zones, _ = pending
            for z in zones_to_reset(ctrl, start_zones, list(data.get("zones") or []),
                                    self.rt.is_online(ctrl)):
                await self._call(SI_DOMAIN, "set_bucket", {"entity_id": z.si_sensor})
        if _no_zone(data):
            duration = int(_num((data.get("run") or {}).get("duration"), 0))
            await self._log(ctrl, format_line("ctrl_finish", ctrl.name, sequence=seq_name, duration=duration))
            await self._notify(ctrl, self.rt.texts(
                "notify.run_finish", ctrl=ctrl.name, seq=seq_name, minutes=round(duration / 60)))

    async def _on_cancel(self, ctrl: Controller, data: dict, _etype: str) -> None:
        # A cancelled run keeps its deficit: no bucket reset.
        self._si_pending.pop(data.get("entity_id", ""), None)
        if _no_zone(data):
            seq_name = (data.get("sequence") or {}).get("name", "")
            await self._notify(ctrl, self.rt.texts("notify.run_cancelled", ctrl=ctrl.name, seq=seq_name))

    async def _on_valve(self, ctrl: Controller, data: dict, etype: str) -> None:
        run_type = data.get("type")
        typ = str(run_type) if run_type not in (None, 1, "1") else ""
        await self._log(ctrl, format_line(
            "valve_on" if etype == EVENT_IU_VALVE_ON else "valve_off",
            ctrl.name,
            zone=(data.get("zone") or {}).get("name", ""),
            entity=data.get("entity_id", ""),
            duration=data.get("duration", 0),
            run_type=typ,
        ))
