"""Shared fixtures."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

TOPOLOGY = {
    "controllers": [
        {
            "id": "alpha",
            "name": "Controller Alpha",
            "entity_id": "switch.pump_a",
            "zones": [
                {"id": 1, "name": "Lawn", "entity_id": "switch.valve_a1", "si_sensor": "sensor.smart_irrigation_lawn"},
                {"id": 2, "name": "Beds", "entity_id": "switch.valve_a2"},
            ],
            "programs": [{"id": 1, "name": "Morning", "default_time": "04:00"},
                         {"id": 2, "name": "Evening", "default_time": "20:00"}],
            "fill_switches": ["switch.fill_a"],
            "fill_lead_minutes": 120,
            "fill_duration_minutes": 90,
            "availability_entity": "binary_sensor.esp_a_status",
        },
        {
            "id": "beta",
            "name": "Controller Beta",
            "entity_id": "switch.pump_b",
            "zones": [{"id": 1, "name": "Hedge", "entity_id": "switch.valve_b1"}],
            "programs": [{"id": 1, "name": "Morning", "default_time": "08:00"}],
        },
    ],
    "options": {"engine_enabled": True, "notify_entities": ["notify.phone"],
                "notify_persistent": False, "rain_now_entity": "binary_sensor.raining"},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
