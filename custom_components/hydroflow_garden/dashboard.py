"""Generate the irrigation dashboard (Lovelace, storage mode).

Rendered from the Jinja templates in ``dashboard_templates/``: four views per
controller (today, programs, zones, settings), built with custom button-card
only; apexcharts-card is optional, for the history chart of the zones view.
The colours come from ``palettes.py`` and follow the theme and mode chosen
in two hub selects, live in every card.

It is rewritten whenever the configuration that shapes it changes
(controllers, zones, programs, options, the theme selects) and on demand
(button / ``hydroflow_garden.regenerate_dashboard``). Edits made by hand
survive until the next such change.

Lovelace keeps its dashboards collection private, so the dashboard is
registered the way Lovelace registers a storage dashboard: a LovelaceStorage
object in ``hass.data[LOVELACE_DATA].dashboards`` plus a frontend panel. Only
the dashboard registered by this integration (id ``hydroflow_garden_<url>``) is
ever written: when the configured URL belongs to another dashboard, nothing is
saved and a repair issue asks to pick another URL.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DASHBOARD_URL,
    CONF_NOTIFY_ENTITIES,
    CONF_NOTIFY_PERSISTENT,
    CONF_NOTIFY_SERVICES,
    DASHBOARD_MODE_KEY,
    DASHBOARD_THEME_KEY,
    DOMAIN,
    MONTH_CODES,
    SI_ADJUST_LEAD_KEY,
    WEEKDAY_CODES,
)
from .model import Controller, Zone, slugify, zone_sensor_object_id
from .palettes import MODES, PALETTES, THEMES, TOKENS, view_background

_LOGGER = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "dashboard_templates"
REQUIRED_CARDS = ("button-card",)
# Optional: without it the history chart of the zones view is left out.
APEXCHARTS = "apexcharts-card"

THEME_ENTITY = f"select.{DASHBOARD_THEME_KEY}"
MODE_ENTITY = f"select.{DASHBOARD_MODE_KEY}"

# (key, template, path suffix). The first view keeps the path of the old
# single view, so existing links still land on the controller.
VIEWS = (
    ("today", "view_today", ""),
    ("programs", "view_programs", "-programmi"),
    ("zones", "view_zones", "-zone"),
    ("settings", "view_settings", "-impostazioni"),
)


@dataclass
class _ZoneView:
    """Entity ids of one zone, as the templates need them."""

    zone: Zone
    ctrl: Controller
    n: int  # IU controller number (c<N>)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.zone, name)

    @property
    def label(self) -> str:
        return f"Z{self.zone.id} {self.zone.name}"

    @property
    def iu(self) -> str:
        return f"binary_sensor.irrigation_unlimited_c{self.n}_z{self.zone.id}"

    @property
    def planned(self) -> str:
        return "sensor." + zone_sensor_object_id(self.ctrl, self.zone, "Programmato")

    @property
    def usage(self) -> list[str]:
        """Usage sensors: today, yesterday, two days ago."""
        return ["sensor." + zone_sensor_object_id(self.ctrl, self.zone, s) for s in ("Oggi", "Ieri", "2gg fa")]

    @property
    def today(self) -> str:
        return self.usage[0]

    @property
    def si(self) -> str:
        return self.zone.si_sensor

    @property
    def ref(self) -> dict[str, Any]:
        return {"id": self.zone.id, "name": self.label, "entity": self.iu, "planned": self.planned}

    @property
    def programs(self) -> list[dict[str, Any]]:
        c, z = self.ctrl.id, self.zone.id
        return [{
            "name": f"P{p.id} {p.name}",
            "enabled": f"switch.iu_{c}_p{p.id}_enabled",
            "zone_enabled": f"switch.iu_{c}_p{p.id}_z{z}_enabled",
            "duration": f"number.iu_{c}_p{p.id}_z{z}_duration",
            "days": [f"switch.iu_{c}_p{p.id}_z{z}_{d}" for d in WEEKDAY_CODES],
        } for p in self.ctrl.programs]

    @property
    def program_switches(self) -> list[str]:
        return [e for p in self.programs for e in (p["enabled"], p["zone_enabled"])]

    @property
    def watch(self) -> list[str]:
        """Everything the zone cards read: triggers_update."""
        extra = [self.planned, *self.usage, *([self.si] if self.si else [])]
        return extra + [e for p in self.programs for e in (p["enabled"], p["zone_enabled"], p["duration"], *p["days"])]


@dataclass
class _ProgramEntities:
    zone_enabled: list[str]
    zone_duration: list[str]
    zone_days: list[str]
    months: list[str]


@dataclass
class _CtrlView:
    """What the templates read of a controller."""

    ctrl: Controller
    iu_index: int

    def __getattr__(self, name: str) -> Any:
        return getattr(self.ctrl, name)

    @property
    def n(self) -> int:
        return self.iu_index + 1

    @property
    def cm(self) -> str:
        return f"binary_sensor.irrigation_unlimited_c{self.n}_m"

    @property
    def seq_base(self) -> str:
        return f"binary_sensor.irrigation_unlimited_c{self.n}_s"

    @property
    def paths(self) -> dict[str, str]:
        return {key: f"irrigazione-{self.ctrl.id}{suffix}" for key, _, suffix in VIEWS}

    @property
    def zones_v(self) -> list[_ZoneView]:
        return [_ZoneView(z, self.ctrl, self.n) for z in self.ctrl.zones]

    @property
    def program_switches(self) -> list[str]:
        return [e for z in self.zones_v for e in z.program_switches]

    def program_entities(self, pid: int) -> _ProgramEntities:
        px = f"iu_{self.ctrl.id}_p{pid}"
        zones = [z.id for z in self.ctrl.zones]
        return _ProgramEntities(
            zone_enabled=[f"switch.{px}_z{z}_enabled" for z in zones],
            zone_duration=[f"number.{px}_z{z}_duration" for z in zones],
            zone_days=[f"switch.{px}_z{z}_{d}" for z in zones for d in WEEKDAY_CODES],
            months=[f"switch.{px}_{m}" for m in MONTH_CODES],
        )


def _env(texts: dict[str, Any]) -> jinja2.Environment:
    """``texts``: the ``dashboard`` texts of one language (texts/<lang>.json)."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["slugify"] = slugify
    # Quoted literal, valid both as a YAML double-quoted scalar and in JS.
    env.filters["q"] = lambda v: json.dumps(v, ensure_ascii=False)
    env.globals.update(
        t=texts,
        weekdays=list(zip(WEEKDAY_CODES, texts["weekdays_short"], strict=True)),
        months=list(zip(MONTH_CODES, texts["months_short"], strict=True)),
        tokens=TOKENS,
        themes=THEMES,
        modes=MODES,
        palettes_js=json.dumps(PALETTES, separators=(",", ":")),
        theme_entity=THEME_ENTITY,
        mode_entity=MODE_ENTITY,
        si_lead_entity=f"number.{SI_ADJUST_LEAD_KEY}",
        nav_items=[(key, texts["views"][key]) for key, _, _ in VIEWS],
    )
    return env


def render_dashboard(
    controllers: list[Controller], title: str, texts: dict[str, Any], has_apexcharts: bool = True,
    url: str = "hydroflow-garden", theme: str | None = None, mode: str | None = None,
    notify_targets: list[str] | None = None,
) -> dict:
    """Full Lovelace config (pure, blocking: run in an executor).

    ``theme`` / ``mode``: current values of the appearance selects, only used
    for the page colour (the cards read the selects live). ``notify_targets``:
    where notifications go, shown in the settings (options change -> reload ->
    new render)."""
    env = _env(texts)
    env.globals.update(has_apexcharts=has_apexcharts, url=url, domain=DOMAIN,
                       notify_targets=list(notify_targets or []))
    background = view_background(theme, mode)
    many = len(controllers) > 1
    views = []
    for pos, ctrl in enumerate(controllers):
        cv = _CtrlView(ctrl, pos)
        for key, template, _ in VIEWS:
            label = texts["views"][key]
            view: dict[str, Any] = {
                "title": ctrl.name if key == "today" else (f"{ctrl.name} · {label}" if many else label),
                "path": cv.paths[key],
                "type": "sections",
                "max_columns": 3,
                "sections": yaml.safe_load(env.get_template(f"{template}.yaml.j2").render(ctrl=cv)),
            }
            if key == "today":
                view["icon"] = "mdi:sprinkler-variant"
            else:
                # Reached through the in-page header. A subview never gets a
                # tab (a hidden view still shows one while open): HA shows a
                # back arrow to the controller instead.
                view["subview"] = True
                view["back_path"] = f"/{url}/{cv.paths['today']}"
            if background:
                view["background"] = background
            views.append(view)
    templates = yaml.safe_load(env.get_template("button_templates.yaml.j2").render())
    return {"title": title, "button_card_templates": templates, "views": views}


def _notify_targets(rt) -> list[str]:
    """Notification targets of the hub options, as the settings view lists them."""
    out = [*rt.options.get(CONF_NOTIFY_ENTITIES, []), *rt.options.get(CONF_NOTIFY_SERVICES, [])]
    if rt.options.get(CONF_NOTIFY_PERSISTENT):
        out.append(rt.texts("dashboard.notify_persistent"))
    return out


def _lovelace(hass: HomeAssistant):
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    return hass.data.get(LOVELACE_DATA)


def _dashboard_id(url: str) -> str:
    return f"{DOMAIN}_{slugify(url)}"


class DashboardUrlTaken(Exception):
    """The configured URL belongs to a dashboard this integration did not create."""


async def _async_get_or_register(rt) -> Any:
    """The dashboard of this integration, None when Lovelace is not loaded.
    Raises DashboardUrlTaken when the URL is used by another dashboard."""
    from homeassistant.components.lovelace.const import MODE_STORAGE
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    hass = rt.hass
    data = _lovelace(hass)
    if data is None:
        _LOGGER.warning("Lovelace not loaded: dashboard not generated")
        return None
    url = rt.options[CONF_DASHBOARD_URL]
    existing = data.dashboards.get(url)
    if existing is not None:
        own = (existing.mode == MODE_STORAGE
               and (getattr(existing, "config", None) or {}).get("id") == _dashboard_id(url))
        if not own:
            raise DashboardUrlTaken(url)
        return existing
    item = {
        "id": _dashboard_id(url),
        "url_path": url,
        "title": rt.dashboard_title,
        "icon": "mdi:sprinkler-variant",
        "show_in_sidebar": True,
        "require_admin": False,
        "mode": MODE_STORAGE,
    }
    dash = LovelaceStorage(hass, item)
    data.dashboards[url] = dash
    frontend.async_register_built_in_panel(
        hass, "lovelace", frontend_url_path=url, require_admin=False,
        show_in_sidebar=True, sidebar_title=item["title"], sidebar_icon=item["icon"],
        config={"mode": MODE_STORAGE}, update=False,
    )
    rt.dashboard_registered = url
    return dash


def _resource_urls(rt) -> list[str] | None:
    """URLs of the Lovelace resources, None when they cannot be read."""
    data = _lovelace(rt.hass)
    try:
        return [str(r.get("url", "")) for r in data.resources.async_items()]
    except Exception:  # noqa: BLE001 - resources not loaded yet, or YAML mode
        return None


def _check_resources(rt, urls: list[str] | None) -> None:
    if urls is None:
        return
    missing = [c for c in REQUIRED_CARDS if not any(c in u for u in urls)]
    if missing:
        ir.async_create_issue(
            rt.hass, DOMAIN, "missing_cards", is_fixable=False,
            severity=ir.IssueSeverity.WARNING, translation_key="missing_cards",
            translation_placeholders={"cards": ", ".join(missing)},
        )
    else:
        ir.async_delete_issue(rt.hass, DOMAIN, "missing_cards")


async def async_generate_dashboard(rt, force: bool = True) -> bool:
    """Render and save; with ``force`` False only when the render changed.

    When the URL belongs to another dashboard nothing is written: a repair
    issue is raised, and with ``force`` (button / service) an error too."""
    hass = rt.hass
    urls = _resource_urls(rt)
    # Unknown resources: keep the chart rather than silently drop it.
    has_apex = urls is None or any(APEXCHARTS in u for u in urls)
    config = await hass.async_add_executor_job(
        render_dashboard, rt.controller_list, rt.dashboard_title, rt.texts.data["dashboard"], has_apex,
        rt.options[CONF_DASHBOARD_URL], rt.values.get(DASHBOARD_THEME_KEY), rt.values.get(DASHBOARD_MODE_KEY),
        _notify_targets(rt))
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{rt.entry.entry_id}.dashboard")
    saved = (await store.async_load()) or {}
    url = rt.options[CONF_DASHBOARD_URL]
    try:
        dash = await _async_get_or_register(rt)
    except DashboardUrlTaken:
        _LOGGER.warning("Dashboard %s exists and was not created by %s: not overwritten", url, DOMAIN)
        ir.async_create_issue(
            hass, DOMAIN, "dashboard_url_taken", is_fixable=False,
            severity=ir.IssueSeverity.ERROR, translation_key="dashboard_url_taken",
            translation_placeholders={"url": url},
        )
        if force:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="dashboard_url_taken",
                translation_placeholders={"url": url},
            ) from None
        return False
    ir.async_delete_issue(hass, DOMAIN, "dashboard_url_taken")
    if dash is None:
        return False
    _check_resources(rt, urls)
    if not force and saved.get("digest") == digest and saved.get("url") == rt.options[CONF_DASHBOARD_URL]:
        return False
    await dash.async_save(config)
    await store.async_save({"digest": digest, "url": rt.options[CONF_DASHBOARD_URL]})
    _LOGGER.info("Dashboard %s regenerated", rt.options[CONF_DASHBOARD_URL])
    return True


async def async_dashboard_on_setup(rt) -> None:
    rt.entry.async_on_unload(lambda: _unregister(rt))
    if not rt.controllers:
        return

    @callback
    def _appearance_changed(_key: str, _value: Any) -> None:
        # The cards follow the selects live; only the page colour is static.
        rt.entry.async_create_background_task(
            rt.hass, _async_regenerate_quietly(rt), f"{DOMAIN}_dashboard_appearance")

    for key in (DASHBOARD_THEME_KEY, DASHBOARD_MODE_KEY):
        rt.entry.async_on_unload(rt.values.listen(_appearance_changed, key))
    try:
        await async_generate_dashboard(rt, force=False)
    except Exception:  # noqa: BLE001 - the dashboard must never block the setup
        _LOGGER.exception("Dashboard generation failed")


async def _async_regenerate_quietly(rt) -> None:
    try:
        await async_generate_dashboard(rt, force=False)
    except Exception:  # noqa: BLE001 - a theme change must never raise
        _LOGGER.exception("Dashboard generation failed")


def _unregister(rt) -> None:
    url = getattr(rt, "dashboard_registered", None)
    if not url:
        return
    data = _lovelace(rt.hass)
    if data is not None:
        data.dashboards.pop(url, None)
    frontend.async_remove_panel(rt.hass, url)
