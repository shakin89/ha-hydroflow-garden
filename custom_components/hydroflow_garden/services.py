"""Action names and fields, as listed in services.yaml."""

from __future__ import annotations

from enum import StrEnum


class HydroflowGardenService(StrEnum):
    """Actions registered by the integration."""

    REGENERATE_DASHBOARD = "regenerate_dashboard"
    GET_IU_CONFIG = "get_iu_config"
    RAIN_SKIP = "rain_skip"


class HydroflowGardenServiceArgument(StrEnum):
    """Fields of the actions."""

    FORCE = "force"
