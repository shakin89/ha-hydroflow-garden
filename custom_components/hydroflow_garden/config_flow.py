"""Config flow: one hub entry (global settings), one subentry per controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    CONF_DASHBOARD_TITLE,
    CONF_DASHBOARD_URL,
    CONF_ENGINE_ENABLED,
    CONF_IU_CONFIG_PATH,
    CONF_LOG_KEEP,
    CONF_LOG_MAX_MB,
    CONF_LOG_PATH,
    CONF_MM_THRESHOLD,
    CONF_NOTIFY_ENTITIES,
    CONF_NOTIFY_PERSISTENT,
    CONF_NOTIFY_SERVICES,
    CONF_PROB_THRESHOLD,
    CONF_RAIN_NOW_ENTITY,
    CONF_RAIN_NOW_STATE,
    CONF_SKIP_HOURS,
    CONF_SKIP_TIME,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    HUB_DEFAULTS,
    SUBENTRY_CONTROLLER,
)
from .model import slugify

TITLE = "HydroFlow Garden: Smart and Unlimited"


def _num(mn: float, mx: float, step: float = 1, unit: str | None = None) -> sel.NumberSelector:
    cfg: dict[str, Any] = {"min": mn, "max": mx, "step": step, "mode": "box"}
    if unit:
        cfg["unit_of_measurement"] = unit
    return sel.NumberSelector(sel.NumberSelectorConfig(**cfg))


def _opt(key: str, values: dict) -> vol.Optional:
    """Optional field pre-filled with the current value (empty allowed)."""
    current = values.get(key)
    if current in (None, "", []):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": current})


def hub_schema(values: dict) -> vol.Schema:
    v = {**HUB_DEFAULTS, **values}
    return vol.Schema({
        vol.Required(CONF_ENGINE_ENABLED, default=v[CONF_ENGINE_ENABLED]): sel.BooleanSelector(),
        _opt(CONF_NOTIFY_ENTITIES, v): sel.EntitySelector(
            sel.EntitySelectorConfig(domain="notify", multiple=True)),
        _opt(CONF_NOTIFY_SERVICES, v): sel.TextSelector(sel.TextSelectorConfig(multiple=True)),
        vol.Required(CONF_NOTIFY_PERSISTENT, default=v[CONF_NOTIFY_PERSISTENT]): sel.BooleanSelector(),
        _opt(CONF_WEATHER_ENTITY, v): sel.EntitySelector(sel.EntitySelectorConfig(domain="weather")),
        _opt(CONF_RAIN_NOW_ENTITY, v): sel.EntitySelector(),
        vol.Required(CONF_RAIN_NOW_STATE, default=v[CONF_RAIN_NOW_STATE]): sel.TextSelector(),
        vol.Required(CONF_PROB_THRESHOLD, default=v[CONF_PROB_THRESHOLD]): _num(0, 100, 1, "%"),
        vol.Required(CONF_MM_THRESHOLD, default=v[CONF_MM_THRESHOLD]): _num(0, 100, 0.1, "mm"),
        vol.Required(CONF_SKIP_TIME, default=v[CONF_SKIP_TIME]): sel.TimeSelector(),
        vol.Required(CONF_SKIP_HOURS, default=v[CONF_SKIP_HOURS]): _num(1, 72, 1, "h"),
        vol.Required(CONF_LOG_PATH, default=v[CONF_LOG_PATH]): sel.TextSelector(),
        vol.Required(CONF_LOG_MAX_MB, default=v[CONF_LOG_MAX_MB]): _num(1, 500, 1, "MB"),
        vol.Required(CONF_LOG_KEEP, default=v[CONF_LOG_KEEP]): _num(0, 20),
        vol.Required(CONF_IU_CONFIG_PATH, default=v[CONF_IU_CONFIG_PATH]): sel.TextSelector(),
        vol.Required(CONF_DASHBOARD_URL, default=v[CONF_DASHBOARD_URL]): sel.TextSelector(),
        vol.Required(CONF_DASHBOARD_TITLE, default=v[CONF_DASHBOARD_TITLE]): sel.TextSelector(),
    })


def _clean_hub(data: dict) -> dict:
    out = {**HUB_DEFAULTS, **data}
    for key in (CONF_WEATHER_ENTITY, CONF_RAIN_NOW_ENTITY):
        out[key] = data.get(key) or ""
    for key in (CONF_NOTIFY_ENTITIES, CONF_NOTIFY_SERVICES):
        out[key] = [s for s in (data.get(key) or []) if s]
    for key in (CONF_PROB_THRESHOLD, CONF_SKIP_HOURS, CONF_LOG_KEEP, CONF_LOG_MAX_MB):
        out[key] = int(out[key])
    out[CONF_MM_THRESHOLD] = float(out[CONF_MM_THRESHOLD])
    return out


class IrrigationManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=_clean_hub(user_input))
        return self.async_show_form(step_id="user", data_schema=hub_schema({}))

    async def async_step_import(self, import_data: dict) -> ConfigFlowResult:
        """configuration.yaml ``hydroflow_garden:`` → entry + controllers."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        subentries = []
        for order, ctrl in enumerate(import_data["controllers"]):
            data = dict(ctrl)
            data["order"] = order
            data.setdefault("iu_controller_id", slugify(data["name"]))
            subentries.append({
                "subentry_type": SUBENTRY_CONTROLLER,
                "title": data["name"],
                "unique_id": data["id"],
                "data": data,
            })
        return self.async_create_entry(
            title=TITLE, data={"seed": dict(import_data.get("values", {}))},
            options=_clean_hub(import_data.get("options", {})),
            subentries=subentries,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HubOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry):
        return {SUBENTRY_CONTROLLER: ControllerSubentryFlow}


class HubOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean_hub(user_input))
        return self.async_show_form(step_id="init", data_schema=hub_schema(dict(self.config_entry.options)))


ZONE_FIELDS = {
    "id": {"required": True, "selector": {"number": {"min": 1, "max": 99, "mode": "box"}}},
    "name": {"required": True, "selector": {"text": {}}},
    "entity_id": {"required": True, "selector": {"entity": {"domain": ["switch", "valve"]}}},
    "si_sensor": {"required": False, "selector": {"entity": {"domain": "sensor",
                                                              "integration": "smart_irrigation"}}},
}
PROGRAM_FIELDS = {
    "id": {"required": True, "selector": {"number": {"min": 1, "max": 9, "mode": "box"}}},
    "name": {"required": True, "selector": {"text": {}}},
    "default_time": {"required": False, "selector": {"time": {}}},
}


def controller_schema(v: dict, creating: bool) -> vol.Schema:
    fields: dict = {}
    if creating:
        fields[vol.Required("name", default=v.get("name", ""))] = sel.TextSelector()
    else:
        fields[vol.Required("name", default=v["name"])] = sel.TextSelector()
    fields.update({
        vol.Required("iu_controller_id", default=v.get("iu_controller_id", "")): sel.TextSelector(),
        vol.Required("entity_id", default=v.get("entity_id", "")): sel.EntitySelector(
            sel.EntitySelectorConfig(domain=["switch", "valve"])),
        vol.Required("max_zone_duration", default=v.get("max_zone_duration", "00:40")): sel.TextSelector(),
        vol.Required("zones", default=v.get("zones", [])): sel.ObjectSelector(
            sel.ObjectSelectorConfig(fields=ZONE_FIELDS, multiple=True, label_field="name")),
        vol.Required("programs", default=v.get("programs", [
            {"id": 1, "name": "Mattina", "default_time": "06:00"},
            {"id": 2, "name": "Sera", "default_time": "20:00"},
        ])): sel.ObjectSelector(
            sel.ObjectSelectorConfig(fields=PROGRAM_FIELDS, multiple=True, label_field="name")),
        _opt("fill_switches", v): sel.EntitySelector(
            sel.EntitySelectorConfig(domain="switch", multiple=True)),
        vol.Required("fill_lead_minutes", default=v.get("fill_lead_minutes", 120)): _num(0, 240, 5, "min"),
        vol.Required("fill_duration_minutes", default=v.get("fill_duration_minutes", 90)): _num(0, 240, 5, "min"),
        _opt("availability_entity", v): sel.EntitySelector(
            sel.EntitySelectorConfig(domain="binary_sensor")),
        vol.Required("preflight_timeout_minutes", default=v.get("preflight_timeout_minutes", 15)): _num(1, 60, 1, "min"),
    })
    return vol.Schema(fields)


def _validate_controller(data: dict) -> tuple[dict, dict[str, str]]:
    errors: dict[str, str] = {}
    zones, programs = [], []
    for z in data.get("zones") or []:
        zones.append({"id": int(z["id"]), "name": str(z["name"]).strip(),
                      "entity_id": z["entity_id"], "si_sensor": z.get("si_sensor") or ""})
    for p in data.get("programs") or []:
        t = str(p.get("default_time") or "06:00")[:5]
        programs.append({"id": int(p["id"]), "name": str(p["name"]).strip(), "default_time": t})
    if not zones:
        errors["zones"] = "no_zones"
    elif len({z["id"] for z in zones}) != len(zones):
        errors["zones"] = "duplicate_id"
    if not programs:
        errors["programs"] = "no_programs"
    elif len({p["id"] for p in programs}) != len(programs):
        errors["programs"] = "duplicate_id"
    out = {
        **data,
        "iu_controller_id": slugify(data.get("iu_controller_id") or data["name"]),
        "zones": sorted(zones, key=lambda z: z["id"]),
        "programs": sorted(programs, key=lambda p: p["id"]),
        "fill_switches": list(data.get("fill_switches") or []),
        "availability_entity": data.get("availability_entity") or "",
        "fill_lead_minutes": int(data.get("fill_lead_minutes", 120)),
        "fill_duration_minutes": int(data.get("fill_duration_minutes", 90)),
        "preflight_timeout_minutes": int(data.get("preflight_timeout_minutes", 15)),
    }
    return out, errors


class ControllerSubentryFlow(ConfigSubentryFlow):
    """Create / reconfigure one controller with its zones and programs.

    Zone and program ids are part of every value key: changing the id of a
    zone means a new zone (its values and history start over).
    """

    async def async_step_user(self, user_input: dict | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_controller(user_input)
            data["id"] = slugify(user_input.get("id") or user_input["name"])
            taken = {s.data.get("id") for s in entry.subentries.values()}
            if data["id"] in taken:
                errors["name"] = "already_configured"
            if not errors:
                data["order"] = 1 + max(
                    [int(s.data.get("order", 0)) for s in entry.subentries.values()], default=-1)
                return self.async_create_entry(title=data["name"], data=data, unique_id=data["id"])
        schema = controller_schema(user_input or {}, creating=True).extend(
            {vol.Optional("id"): sel.TextSelector()})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        current = dict(subentry.data)
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_controller(user_input)
            if not errors:
                data["id"] = current["id"]
                data["order"] = current.get("order", 0)
                return self.async_update_and_abort(entry, subentry, title=data["name"], data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=controller_schema(user_input or current, creating=False),
            errors=errors,
        )
