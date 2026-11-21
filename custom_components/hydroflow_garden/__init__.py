"""HydroFlow Garden: plans Irrigation Unlimited from the UI."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, Platform
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from . import i18n
from .const import DOMAIN, REASON_NONE
from .model import suspend_reason_key
from .runtime import HUB_SPECS, IrrigationRuntime, controllers_of
from .services import HydroflowGardenService, HydroflowGardenServiceArgument
from .values import ValueStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

# One-time import of an existing topology from configuration.yaml; remove the
# block afterwards. The structure mirrors the controller subentry data.
_ZONE = vol.Schema({
    vol.Required("id"): vol.Coerce(int),
    vol.Required("name"): cv.string,
    vol.Required("entity_id"): cv.entity_id,
    vol.Optional("si_sensor", default=""): vol.Any("", cv.entity_id),
})
_PROGRAM = vol.Schema({
    vol.Required("id"): vol.Coerce(int),
    vol.Required("name"): cv.string,
    vol.Optional("default_time", default="06:00"): cv.string,
})
_CONTROLLER = vol.Schema({
    vol.Required("id"): cv.slug,
    vol.Required("name"): cv.string,
    vol.Optional("iu_controller_id"): cv.slug,
    vol.Required("entity_id"): cv.entity_id,
    vol.Optional("max_zone_duration", default="00:40"): cv.string,
    vol.Required("zones"): [_ZONE],
    vol.Required("programs"): [_PROGRAM],
    vol.Optional("fill_switches", default=[]): cv.entity_ids,
    vol.Optional("fill_lead_minutes", default=120): vol.Coerce(int),
    vol.Optional("fill_duration_minutes", default=90): vol.Coerce(int),
    vol.Optional("availability_entity", default=""): vol.Any("", cv.entity_id),
    vol.Optional("preflight_timeout_minutes", default=15): vol.Coerce(int),
})
CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({
        vol.Required("controllers"): [_CONTROLLER],
        vol.Optional("options", default={}): dict,
        # initial values by key (e.g. iu_garden_p1_z1_mon: true), used once
        vol.Optional("values", default={}): {cv.string: vol.Any(bool, int, float, str)},
    })},
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    if DOMAIN in config:
        if hass.config_entries.async_entries(DOMAIN):
            _LOGGER.warning(
                "'%s:' in configuration.yaml ignored: the integration is already set up. "
                "The YAML block is a one-time import; remove it, or delete the entry "
                "and restart to import again", DOMAIN)
        else:
            hass.async_create_task(hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]))
    _register_services(hass)
    return True


def _runtime(hass: HomeAssistant) -> IrrigationRuntime:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


def _register_services(hass: HomeAssistant) -> None:
    async def regenerate_dashboard(call: ServiceCall) -> None:
        from .dashboard import async_generate_dashboard
        await async_generate_dashboard(_runtime(hass))

    async def get_iu_config(call: ServiceCall):
        """The text of the file included by ``irrigation_unlimited:``. The
        integration never writes it: the user pastes it."""
        rt = _runtime(hass)
        return {"yaml": rt.iu_structure_text(),
                "in_sync": [c.name for c in rt.controller_list if rt.iu_structure_ok(c)]}

    async def rain_skip(call: ServiceCall):
        rt = _runtime(hass)
        if rt.engine is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="engine_off")
        skipped = await rt.engine.async_rain_skip(force=call.data[HydroflowGardenServiceArgument.FORCE])
        return {"skipped": skipped, "forecast": rt.forecast}

    hass.services.async_register(
        DOMAIN, HydroflowGardenService.REGENERATE_DASHBOARD, regenerate_dashboard)
    hass.services.async_register(DOMAIN, HydroflowGardenService.GET_IU_CONFIG, get_iu_config,
                                 supports_response=SupportsResponse.ONLY)
    hass.services.async_register(
        DOMAIN, HydroflowGardenService.RAIN_SKIP, rain_skip,
        schema=vol.Schema({
            vol.Optional(HydroflowGardenServiceArgument.FORCE, default=False): cv.boolean}),
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Up to 0.4.0-beta.2 a button rewrote the IU file.
    reg = er.async_get(hass)
    if old := reg.async_get_entity_id("button", DOMAIN, "iu_write_config"):
        reg.async_remove(old)
    values = ValueStore(hass, entry.entry_id)
    specs = {s.key: s for s in HUB_SPECS}
    extra = {}
    from .model import controller_specs
    for _, ctrl in controllers_of(entry):
        specs.update({s.key: s for s in controller_specs(ctrl)})
        extra[suspend_reason_key(ctrl)] = REASON_NONE
    seeded = await values.async_load(specs, extra, dict(entry.data.get("seed", {})))
    if seeded:
        _LOGGER.info("Seeded %s values (import or existing input_* helpers)", len(seeded))

    lang = i18n.language(hass.config.language)
    texts = i18n.Texts(lang, await hass.async_add_executor_job(i18n.load, lang))
    rt = IrrigationRuntime(hass, entry, values, texts)
    entry.runtime_data = rt
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await rt.async_start()
    if rt.engine_enabled:
        from .engine import Engine
        rt.engine = Engine(rt)
        await rt.engine.async_start()

    from .dashboard import async_dashboard_on_setup
    await async_dashboard_on_setup(rt)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    @callback
    def _core_config_updated(_event: Event) -> None:
        # Notifications and the dashboard are rendered in the language of HA.
        if i18n.language(hass.config.language) != rt.texts.lang:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _core_config_updated))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    rt: IrrigationRuntime = entry.runtime_data
    if rt.engine is not None:
        await rt.engine.async_stop()
    await rt.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await ValueStore(hass, entry.entry_id).async_remove()
