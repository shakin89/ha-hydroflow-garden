"""Runtime state of one config entry: topology, values, IU sync, observers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DOMAIN, ATTR_SERVICE, EVENT_CALL_SERVICE, STATE_ON
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import iu_config
from .const import (
    CONF_DASHBOARD_TITLE,
    CONF_ENGINE_ENABLED,
    CONF_LOG_KEEP,
    CONF_LOG_MAX_MB,
    CONF_LOG_PATH,
    CONF_RAIN_NOW_ENTITY,
    CONF_RAIN_NOW_STATE,
    CONF_WEATHER_ENTITY,
    DASHBOARD_MODE_KEY,
    DASHBOARD_THEME_KEY,
    DOMAIN,
    HUB_DEFAULTS,
    IU_DOMAIN,
    IU_SYNC_DEBOUNCE,
    REASON_NONE,
    SI_ADJUST_LEAD_DEFAULT,
    SI_ADJUST_LEAD_KEY,
    SUBENTRY_CONTROLLER,
)
from .i18n import Texts
from .iu_config import _num
from .logfile import LogFile
from .model import (
    KIND_SELECT,
    Controller,
    ValueSpec,
    controller_specs,
    suspend_reason_key,
)
from .palettes import MODE_AUTO, MODES, THEME_SYSTEM, THEMES

_LOGGER = logging.getLogger(__name__)

SIGNAL_FORECAST = f"{DOMAIN}_forecast"
SIGNAL_USAGE = f"{DOMAIN}_usage"
SIGNAL_RAIN_NOW = f"{DOMAIN}_rain_now"
SIGNAL_SI_OVERRIDE = f"{DOMAIN}_si_override"

HUB_SPECS = [
    ValueSpec(SI_ADJUST_LEAD_KEY, "number", "si_adjust_lead",
              "mdi:timer-cog-outline", SI_ADJUST_LEAD_DEFAULT, min=1, max=60, step=1,
              unit="min", legacy_domain="input_number"),
    # Read live by the dashboard cards; also rewrites the page colour.
    ValueSpec(DASHBOARD_THEME_KEY, KIND_SELECT, "dashboard_theme", "mdi:palette-outline",
              THEME_SYSTEM, options=tuple(THEMES)),
    ValueSpec(DASHBOARD_MODE_KEY, KIND_SELECT, "dashboard_mode", "mdi:theme-light-dark",
              MODE_AUTO, options=tuple(MODES)),
]


def controllers_of(entry: ConfigEntry) -> list[tuple[str, Controller]]:
    """(subentry_id, controller) in IU order: by the ``order`` field, which is
    assigned once at creation, so IU ``c<N>`` indices stay put."""
    items = [
        (sid, sub) for sid, sub in entry.subentries.items()
        if sub.subentry_type == SUBENTRY_CONTROLLER
    ]
    items.sort(key=lambda it: (int(it[1].data.get("order", 0)), it[1].title))
    return [(sid, Controller.from_dict(dict(sub.data))) for sid, sub in items]


class IrrigationRuntime:
    """Everything the platforms and the engine share."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, values, texts: Texts) -> None:
        self.hass = hass
        self.entry = entry
        self.values = values
        # Notification and dashboard texts in the language of HA
        self.texts = texts
        self.options: dict[str, Any] = {**HUB_DEFAULTS, **entry.options}
        self.controllers: list[tuple[str, Controller]] = controllers_of(entry)
        self.specs: dict[str, ValueSpec] = {s.key: s for s in HUB_SPECS}
        for _, ctrl in self.controllers:
            for spec in controller_specs(ctrl):
                self.specs[spec.key] = spec
        self.log = LogFile(hass, self.options[CONF_LOG_PATH],
                           float(self.options[CONF_LOG_MAX_MB]), int(self.options[CONF_LOG_KEEP]))
        self.forecast: dict[str, Any] = {"mm": None, "prob": None}
        self.usage = ZoneUsage(hass, entry.entry_id, self)
        self._unsubs: list[Callable[[], None]] = []
        self._syncer = Debouncer(
            hass, _LOGGER, cooldown=IU_SYNC_DEBOUNCE, immediate=False,
            function=self.async_sync_iu,
        )
        self._sync_lock = asyncio.Lock()
        # ctrl id -> calls IU has received since it last (re)loaded its file
        self._pushed: dict[str, iu_config.SyncCalls] = {}
        # ctrl id -> {(program id, zone id): seconds per cycle} from Smart Irrigation
        self.si_override: dict[str, dict[tuple[int, int], int]] = {}
        self.engine = None  # set by __init__ when the engine is enabled
        self.dashboard_registered: str | None = None

    # --- helpers -----------------------------------------------------------
    @property
    def engine_enabled(self) -> bool:
        return bool(self.options.get(CONF_ENGINE_ENABLED))

    @property
    def dashboard_title(self) -> str:
        return self.options.get(CONF_DASHBOARD_TITLE) or self.texts("dashboard.title")

    @property
    def controller_list(self) -> list[Controller]:
        return [c for _, c in self.controllers]

    def get(self, key: str) -> Any:
        return self.values.get(key)

    def position(self, ctrl: Controller) -> int:
        return next(i for i, (_, c) in enumerate(self.controllers) if c.id == ctrl.id)

    def controller_by_index(self, index: Any) -> Controller | None:
        try:
            return self.controllers[int(index)][1]
        except (TypeError, ValueError, IndexError):
            return None

    def iu_entity(self, pos: int, suffix: str) -> str:
        """IU entity id by unique_id ``c<N>_<suffix>``, conventional id as fallback."""
        unique_id = f"c{pos + 1}_{suffix}"
        reg = er.async_get(self.hass)
        found = reg.async_get_entity_id("binary_sensor", IU_DOMAIN, unique_id)
        return found or f"binary_sensor.irrigation_unlimited_{unique_id}"

    def master(self, ctrl: Controller) -> str:
        return self.iu_entity(self.position(ctrl), "m")

    def zone_entity(self, ctrl: Controller, zone_id: int) -> str:
        return self.iu_entity(self.position(ctrl), f"z{zone_id}")

    def is_online(self, ctrl: Controller) -> bool:
        """Device of the valves online (True when no probe is configured)."""
        if not ctrl.availability_entity:
            return True
        state = self.hass.states.get(ctrl.availability_entity)
        return state is not None and state.state == STATE_ON

    def rain_now(self) -> bool:
        entity = self.options.get(CONF_RAIN_NOW_ENTITY)
        if not entity:
            return False
        state = self.hass.states.get(entity)
        return state is not None and state.state == str(self.options.get(CONF_RAIN_NOW_STATE, "on"))

    def set_reason(self, ctrl: Controller, reason: str) -> None:
        self.values.set(suspend_reason_key(ctrl), reason)

    # --- IU configuration ---------------------------------------------------
    # The integration never writes the IU file. The user pastes the static
    # structure (iu_config.build_structure) once; schedules, zones and
    # durations reach IU through its services. IU forgets load_schedule on a
    # restart or a reload, so everything is pushed again after both.
    def build_iu(self) -> dict:
        """The configuration IU must end up running."""
        return iu_config.build_config(self.get, self.controller_list)

    def iu_structure_text(self) -> str:
        """The YAML the user pastes as the file included by ``irrigation_unlimited:``."""
        return iu_config.dump(iu_config.build_structure(self.get, self.controller_list))

    def iu_structure_ok(self, ctrl: Controller) -> bool | None:
        """Whether IU runs the current structure of ``ctrl``; None while IU
        has not created the controller entity yet."""
        state = self.hass.states.get(self.master(ctrl))
        if state is None:
            return None
        return state.attributes.get(iu_config.STRUCTURE_ATTR) == iu_config.structure_digest(self.get, ctrl)

    def iu_resync(self) -> None:
        """Forget what IU received and push everything again (debounced)."""
        self._pushed.clear()
        self.hass.async_create_task(self._syncer.async_call())

    async def async_sync_iu(self) -> bool:
        """Push to IU what changed since the last push. Controllers whose IU
        file is outdated are left alone and reported in a repair issue.
        Returns True when every controller is in sync."""
        if not self.engine_enabled:
            return False
        async with self._sync_lock:
            outdated: list[Controller] = []
            for ctrl in self.controller_list:
                ok = self.iu_structure_ok(ctrl)
                if ok is None:
                    continue  # IU not loaded yet: its entity appearing triggers a sync
                if not ok:
                    outdated.append(ctrl)
                    self._pushed.pop(ctrl.id, None)
                    continue
                await self._async_push(ctrl)
            self._update_outdated_issue(outdated)
            return not outdated

    async def _async_push(self, ctrl: Controller) -> None:
        if not self.hass.services.has_service(IU_DOMAIN, "load_schedule"):
            return
        wanted = iu_config.sync_calls(self.get, ctrl, self.si_override.get(ctrl.id))
        pushed = self._pushed.setdefault(ctrl.id, {})
        master = self.master(ctrl)
        for key, call in wanted.items():
            if pushed.get(key) == call:
                continue
            service, data = call
            payload = dict(data) if service == "load_schedule" else {"entity_id": master, **data}
            try:
                await self.hass.services.async_call(IU_DOMAIN, service, payload, blocking=True)
            except Exception as err:  # noqa: BLE001 - keep pushing the rest
                _LOGGER.error("%s.%s %s failed: %s", IU_DOMAIN, service, payload, err)
                continue
            pushed[key] = call

    def _update_outdated_issue(self, outdated: list[Controller]) -> None:
        if not outdated:
            ir.async_delete_issue(self.hass, DOMAIN, "iu_config_outdated")
            return
        ir.async_create_issue(
            self.hass, DOMAIN, "iu_config_outdated", is_fixable=False,
            severity=ir.IssueSeverity.ERROR, translation_key="iu_config_outdated",
            translation_placeholders={
                "controllers": ", ".join(c.name for c in outdated),
                "yaml": self.iu_structure_text(),
            },
        )

    # --- lifecycle ----------------------------------------------------------
    async def async_start(self) -> None:
        @callback
        def _on_value(key: str, _value: Any) -> None:
            spec = self.specs.get(key)
            if spec is not None and spec.schedule and self.engine_enabled:
                self.hass.async_create_task(self._syncer.async_call())

        self._unsubs.append(self.values.listen(_on_value))
        await self.usage.async_start()

        if self.options.get(CONF_WEATHER_ENTITY):
            self._unsubs.append(async_track_time_interval(
                self.hass, self._async_refresh_forecast, timedelta(minutes=30)))
            self.hass.async_create_task(self._async_refresh_forecast())
        rain_entity = self.options.get(CONF_RAIN_NOW_ENTITY)
        if rain_entity:
            @callback
            def _rain(_e: Event[EventStateChangedData]) -> None:
                async_dispatcher_send(self.hass, SIGNAL_RAIN_NOW)
            self._unsubs.append(async_track_state_change_event(self.hass, [rain_entity], _rain))

        # A suspension that ended takes its reason with it, so that a later one
        # made by hand from the IU UI is not labelled with a stale reason.
        masters = {self.master(c): c for c in self.controller_list}

        @callback
        def _master_changed(event: Event[EventStateChangedData]) -> None:
            new = event.data["new_state"]
            ctrl = masters.get(event.data["entity_id"])
            if new is None or ctrl is None:
                return
            old = event.data["old_state"]
            # IU created the controller (startup) or loaded another file.
            if self.engine_enabled and (old is None or old.attributes.get(iu_config.STRUCTURE_ATTR)
                                        != new.attributes.get(iu_config.STRUCTURE_ATTR)):
                self._pushed.pop(ctrl.id, None)
                self.hass.async_create_task(self._syncer.async_call())
            if new.attributes.get("suspended") is None and \
                    self.values.get(suspend_reason_key(ctrl)) != REASON_NONE:
                self.set_reason(ctrl, REASON_NONE)

        if masters:
            self._unsubs.append(async_track_state_change_event(self.hass, list(masters), _master_changed))

        if self.engine_enabled:
            @callback
            def _iu_reloaded(event: Event) -> None:
                if event.data.get(ATTR_DOMAIN) == IU_DOMAIN and event.data.get(ATTR_SERVICE) == "reload":
                    self.iu_resync()

            self._unsubs.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, _iu_reloaded))
            await self.async_sync_iu()
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "iu_config_outdated")

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._syncer.async_shutdown()
        await self.usage.async_stop()
        await self.values.async_flush()

    async def _async_refresh_forecast(self, _now: datetime | None = None) -> None:
        entity = self.options.get(CONF_WEATHER_ENTITY)
        fc = await async_get_today_forecast(self.hass, entity)
        if fc is None:
            return
        self.forecast = fc
        async_dispatcher_send(self.hass, SIGNAL_FORECAST)


async def async_get_today_forecast(hass: HomeAssistant, entity: str) -> dict | None:
    """{'mm', 'prob'} of today's daily forecast (forecast[0]), None on failure."""
    if not entity:
        return None
    try:
        resp = await hass.services.async_call(
            "weather", "get_forecasts", {"entity_id": entity, "type": "daily"},
            blocking=True, return_response=True,
        )
        today = resp[entity]["forecast"][0]
    except Exception as err:  # noqa: BLE001 - weather providers fail in many ways
        _LOGGER.warning("Forecast from %s unavailable: %s", entity, err)
        return None
    return {
        "mm": round(_num(today.get("precipitation"), 0.0), 2),
        "prob": int(_num(today.get("precipitation_probability"), 0)),
    }


class ZoneUsage:
    """Seconds each IU zone was open today, yesterday and two days ago.

    Replaces the history_stats sensors: observes the IU zone entities and
    keeps three daily buckets per zone, persisted across restarts.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str, rt: IrrigationRuntime) -> None:
        self.hass = hass
        self.rt = rt
        self._store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry_id}.usage")
        # zone key -> {"day": iso date, "secs": [today, yesterday, 2 days ago]}
        self._data: dict[str, dict] = {}
        self._on_since: dict[str, datetime] = {}
        self._entity_to_key: dict[str, str] = {}
        self._unsubs: list[Callable[[], None]] = []

    @staticmethod
    def key(ctrl: Controller, zone_id: int) -> str:
        return f"{ctrl.id}_z{zone_id}"

    def _roll(self, key: str) -> dict:
        today = dt_util.now().date()
        rec = self._data.setdefault(key, {"day": today.isoformat(), "secs": [0, 0, 0]})
        last = date.fromisoformat(rec["day"])
        shift = (today - last).days
        if shift > 0:
            rec["secs"] = ([0] * min(shift, 3) + rec["secs"])[:3]
            rec["day"] = today.isoformat()
        return rec

    def seconds(self, ctrl: Controller, zone_id: int, days_ago: int) -> float:
        key = self.key(ctrl, zone_id)
        rec = self._roll(key)
        secs = float(rec["secs"][days_ago])
        if days_ago == 0 and key in self._on_since:
            start = max(self._on_since[key], dt_util.start_of_local_day())
            secs += (dt_util.now() - start).total_seconds()
        return secs

    async def async_start(self) -> None:
        self._data = (await self._store.async_load()) or {}
        saved_at = self._data.pop("_saved_at", None)
        saved = dt_util.parse_datetime(saved_at) if saved_at else None
        for ctrl in self.rt.controller_list:
            for z in ctrl.zones:
                self._entity_to_key[self.rt.zone_entity(ctrl, z.id)] = self.key(ctrl, z.id)
        for entity, key in self._entity_to_key.items():
            st = self.hass.states.get(entity)
            if st is not None and st.state == STATE_ON:
                self._on_since[key] = max(st.last_changed, saved) if saved else st.last_changed
        if self._entity_to_key:
            self._unsubs.append(async_track_state_change_event(
                self.hass, list(self._entity_to_key), self._changed))
        self._unsubs.append(async_track_time_change(self.hass, self._midnight, 0, 0, 5))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        key = self._entity_to_key.get(event.data["entity_id"])
        new = event.data["new_state"]
        if key is None or new is None:
            return
        now = dt_util.now()
        if new.state == STATE_ON and key not in self._on_since:
            self._on_since[key] = now
        elif new.state != STATE_ON and key in self._on_since:
            start = self._on_since.pop(key)
            self._credit(key, start, now)
            self._store.async_delay_save(lambda: self._data, 5)
        async_dispatcher_send(self.hass, SIGNAL_USAGE)

    def _credit(self, key: str, start: datetime, end: datetime) -> None:
        """Split an open interval at midnights into the daily buckets."""
        rec = self._roll(key)
        today0 = dt_util.start_of_local_day()
        for days_ago in range(3):
            day_start = today0 - timedelta(days=days_ago)
            day_end = day_start + timedelta(days=1)
            overlap = (min(end, day_end) - max(start, day_start)).total_seconds()
            if overlap > 0:
                rec["secs"][days_ago] += overlap

    @callback
    def _midnight(self, _now: datetime) -> None:
        now = dt_util.now()
        for key, start in list(self._on_since.items()):
            self._credit(key, start, now)
            self._on_since[key] = now
        for key in [k for k in self._data if not k.startswith("_")]:
            self._roll(key)
        self._store.async_delay_save(lambda: self._data, 5)
        async_dispatcher_send(self.hass, SIGNAL_USAGE)

    @callback
    def _tick(self, _now: datetime) -> None:
        if self._on_since:
            async_dispatcher_send(self.hass, SIGNAL_USAGE)

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        now = dt_util.now()
        for key, start in list(self._on_since.items()):
            self._credit(key, start, now)
            self._on_since[key] = now
        await self._store.async_save({**self._data, "_saved_at": now.isoformat()})
