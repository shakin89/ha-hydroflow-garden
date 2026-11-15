"""Generate the irrigation dashboard (Lovelace, storage mode).

Rendered from the Jinja templates in ``dashboard_templates/`` (custom
button-card, auto-entities and apexcharts-card required). It is rewritten whenever the
configuration that shapes it changes (controllers, zones, programs, options)
and on demand (button / ``irrigation_manager.regenerate_dashboard``). Edits
made by hand survive until the next such change.

Lovelace keeps its dashboards collection private, so the dashboard is
registered the way Lovelace registers a storage dashboard: a LovelaceStorage
object in ``hass.data[LOVELACE_DATA].dashboards`` plus a frontend panel. If a
storage dashboard with the configured URL already exists (e.g. created by
hand), it is written in place instead.
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DASHBOARD_TITLE,
    CONF_DASHBOARD_URL,
    DOMAIN,
    MONTHS,
    TIME_TYPES,
    WEEKDAYS,
)
from .model import Controller, slugify

_LOGGER = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "dashboard_templates"
REQUIRED_CARDS = ("button-card", "auto-entities", "apexcharts-card")


@dataclass
class _CtrlView:
    """What the templates read of a controller."""

    ctrl: Controller
    iu_index: int

    def __getattr__(self, name: str) -> Any:
        return getattr(self.ctrl, name)


def _env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["slugify"] = slugify
    env.globals.update(weekdays=WEEKDAYS, months=MONTHS, time_type_options=TIME_TYPES)
    return env


def render_dashboard(controllers: list[Controller], title: str) -> dict:
    """Full Lovelace config (pure, blocking: run in an executor)."""
    env = _env()
    views = []
    for pos, ctrl in enumerate(controllers):
        view = _CtrlView(ctrl, pos)
        sections = [
            yaml.safe_load(env.get_template(f"{name}.yaml.j2").render(ctrl=view))
            for name in ("status", "programs", "system")
        ]
        views.append({
            "title": ctrl.name,
            "path": f"irrigazione-{ctrl.id}",
            "icon": "mdi:sprinkler",
            "type": "sections",
            "max_columns": 3,
            "sections": sections,
        })
    templates = yaml.safe_load(env.get_template("button_templates.yaml.j2").render())
    return {"title": title, "button_card_templates": templates, "views": views}


def _lovelace(hass: HomeAssistant):
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    return hass.data.get(LOVELACE_DATA)


async def _async_get_or_register(rt) -> Any:
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
        if existing.mode != MODE_STORAGE:
            _LOGGER.warning("Dashboard %s is in YAML mode: not overwritten", url)
            return None
        return existing
    item = {
        "id": f"{DOMAIN}_{slugify(url)}",
        "url_path": url,
        "title": rt.options[CONF_DASHBOARD_TITLE],
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


def _check_resources(rt) -> None:
    data = _lovelace(rt.hass)
    urls = []
    try:
        urls = [str(r.get("url", "")) for r in data.resources.async_items()]
    except Exception:  # noqa: BLE001 - resources not loaded yet
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
    """Render and save; with ``force`` False only when the render changed."""
    hass = rt.hass
    config = await hass.async_add_executor_job(
        render_dashboard, rt.controller_list, rt.options[CONF_DASHBOARD_TITLE])
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{rt.entry.entry_id}.dashboard")
    saved = (await store.async_load()) or {}
    dash = await _async_get_or_register(rt)
    if dash is None:
        return False
    _check_resources(rt)
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
    try:
        await async_generate_dashboard(rt, force=False)
    except Exception:  # noqa: BLE001 - the dashboard must never block the setup
        _LOGGER.exception("Dashboard generation failed")


def _unregister(rt) -> None:
    url = getattr(rt, "dashboard_registered", None)
    if not url:
        return
    data = _lovelace(rt.hass)
    if data is not None:
        data.dashboards.pop(url, None)
    frontend.async_remove_panel(rt.hass, url)
