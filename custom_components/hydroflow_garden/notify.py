"""Send one message to every configured channel."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import CONF_NOTIFY_ENTITIES, CONF_NOTIFY_PERSISTENT, CONF_NOTIFY_SERVICES

_LOGGER = logging.getLogger(__name__)


async def async_notify(hass: HomeAssistant, options: dict, title: str, message: str) -> None:
    """notify.send_message to the notify entities, the legacy notify services
    (e.g. mobile_app) and optionally a persistent notification. A failing
    channel is logged and does not stop the others."""
    calls: list[tuple[str, str, dict]] = []
    entities = options.get(CONF_NOTIFY_ENTITIES) or []
    if entities:
        calls.append(("notify", "send_message",
                      {"entity_id": list(entities), "title": title, "message": message}))
    for svc in options.get(CONF_NOTIFY_SERVICES) or []:
        domain, _, name = str(svc).partition(".")
        if domain and name:
            calls.append((domain, name, {"title": title, "message": message}))
    if options.get(CONF_NOTIFY_PERSISTENT):
        calls.append(("persistent_notification", "create", {"title": title, "message": message}))

    for domain, service, data in calls:
        try:
            await hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # noqa: BLE001 - one channel must not stop the rest
            _LOGGER.warning("Notification via %s.%s failed: %s", domain, service, err)
