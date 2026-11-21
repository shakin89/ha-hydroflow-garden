"""Diagnostics: configuration and state, notification targets redacted."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hydroflow_garden.const import DOMAIN
from custom_components.hydroflow_garden.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import TOPOLOGY


async def test_diagnostics_redacts_notify_targets(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=TOPOLOGY)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["options"]["notify_entities"] == "**REDACTED**"
    assert "notify.phone" not in str(diag)
    assert {c["id"] for c in diag["controllers"]} == {"alpha", "beta"}
    assert diag["engine_running"] is True
    assert isinstance(diag["values"], dict)
