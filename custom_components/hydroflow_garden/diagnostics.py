"""Diagnostics for HydroFlow Garden."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_NOTIFY_ENTITIES, CONF_NOTIFY_SERVICES

# Notification targets can identify the user's phone or account.
TO_REDACT = {CONF_NOTIFY_ENTITIES, CONF_NOTIFY_SERVICES}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return the configuration and the live state of the entry."""
    rt = entry.runtime_data
    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "controllers": [dict(sub.data) for sub in entry.subentries.values()],
        "engine_running": rt.engine is not None,
        "forecast": rt.forecast,
        "values": rt.values.as_dict(),
    }
