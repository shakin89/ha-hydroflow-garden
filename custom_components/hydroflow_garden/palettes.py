"""Dashboard colour themes.

One set of token names for every theme and mode, read by the button-card
templates as CSS custom properties (``--hf-<token>``). ``system`` maps the
tokens to the active Home Assistant theme, so it follows whatever theme and
light/dark mode the user has in HA; the other three are fixed palettes with a
light and a dark variant.

Meaning is fixed across themes: ``water`` = watering now, ``primary`` =
enabled / selected, ``warn`` = suspended, ``danger`` = offline or destructive,
``eco`` = eco and Smart Irrigation. Every text colour is at least 4.5:1 on
``card``.

Pure Python: imported by the dashboard renderer and by the tests.
"""

from __future__ import annotations

import re

THEME_SYSTEM = "system"
THEMES = [THEME_SYSTEM, "salvia", "laguna", "terracotta"]

MODE_AUTO = "auto"
MODE_LIGHT = "light"
MODE_DARK = "dark"
MODES = [MODE_AUTO, MODE_LIGHT, MODE_DARK]

TOKENS = (
    "bg", "card", "inset", "border", "text", "text2",
    "primary", "on_primary", "primary_soft",
    "water", "water_soft", "warn", "warn_soft",
    "danger", "danger_soft", "on_danger", "eco", "eco_soft", "shadow",
)


def _mix(var: str, pct: int = 16) -> str:
    return f"color-mix(in srgb, {var} {pct}%, transparent)"


_SYSTEM = {
    "bg": "var(--primary-background-color)",
    "card": "var(--ha-card-background, var(--card-background-color, #fff))",
    "inset": "var(--secondary-background-color)",
    "border": "var(--divider-color)",
    "text": "var(--primary-text-color)",
    "text2": "var(--secondary-text-color)",
    "primary": "var(--primary-color)",
    "on_primary": "var(--text-primary-color, #fff)",
    "primary_soft": _mix("var(--primary-color)"),
    "water": "var(--info-color, #039be5)",
    "water_soft": _mix("var(--info-color, #039be5)"),
    "warn": "var(--warning-color, #ff9800)",
    "warn_soft": _mix("var(--warning-color, #ff9800)"),
    "danger": "var(--error-color, #db4437)",
    "danger_soft": _mix("var(--error-color, #db4437)"),
    "on_danger": "#fff",
    "eco": "var(--success-color, #43a047)",
    "eco_soft": _mix("var(--success-color, #43a047)"),
    "shadow": "var(--ha-card-box-shadow, none)",
}

PALETTES: dict[str, dict[str, dict[str, str]]] = {
    THEME_SYSTEM: {MODE_LIGHT: _SYSTEM, MODE_DARK: _SYSTEM},
    "salvia": {
        "light": {
            "bg": "#F3F5F0", "card": "#FFFFFF", "inset": "#EDF1E9", "border": "#DCE3D5",
            "text": "#1B2418", "text2": "#4E5A49",
            "primary": "#2E7D4F", "on_primary": "#FFFFFF", "primary_soft": "#E2F0E6",
            "water": "#1B6BAE", "water_soft": "#E1EDF8", "warn": "#8F5600", "warn_soft": "#FBEFD9",
            "danger": "#B83227", "danger_soft": "#FBE6E3", "on_danger": "#FFFFFF",
            "eco": "#4D7A1F", "eco_soft": "#EAF2DC",
            "shadow": "0 1px 2px rgba(27,36,24,0.06), 0 6px 20px rgba(27,36,24,0.06)",
        },
        "dark": {
            "bg": "#0F1411", "card": "#171F1A", "inset": "#212B24", "border": "#2B372F",
            "text": "#E7EEE5", "text2": "#A2B09F",
            "primary": "#6FD39A", "on_primary": "#0A1A10", "primary_soft": "rgba(111,211,154,0.14)",
            "water": "#6DB9F5", "water_soft": "rgba(109,185,245,0.15)",
            "warn": "#F4B860", "warn_soft": "rgba(244,184,96,0.15)",
            "danger": "#FF8177", "danger_soft": "rgba(255,129,119,0.14)", "on_danger": "#2A0A07",
            "eco": "#B4D77A", "eco_soft": "rgba(180,215,122,0.14)",
            "shadow": "none",
        },
    },
    "laguna": {
        "light": {
            "bg": "#F1F5F9", "card": "#FFFFFF", "inset": "#E9EFF5", "border": "#D7E0EA",
            "text": "#0F1E2D", "text2": "#475A6D",
            "primary": "#0A6C9C", "on_primary": "#FFFFFF", "primary_soft": "#E0EEF7",
            "water": "#00796E", "water_soft": "#DDF2EE", "warn": "#8A5300", "warn_soft": "#FCEFD8",
            "danger": "#B8322A", "danger_soft": "#FBE6E4", "on_danger": "#FFFFFF",
            "eco": "#2F7A3E", "eco_soft": "#E3F2E6",
            "shadow": "0 1px 2px rgba(15,30,45,0.06), 0 8px 24px rgba(15,30,45,0.07)",
        },
        "dark": {
            "bg": "#0B1220", "card": "#121C2B", "inset": "#1A2638", "border": "#24324A",
            "text": "#E6EDF5", "text2": "#9DAEC2",
            "primary": "#5CB8F0", "on_primary": "#04192A", "primary_soft": "rgba(92,184,240,0.15)",
            "water": "#4FD6C3", "water_soft": "rgba(79,214,195,0.15)",
            "warn": "#F6BA5E", "warn_soft": "rgba(246,186,94,0.15)",
            "danger": "#FF857B", "danger_soft": "rgba(255,133,123,0.14)", "on_danger": "#2A0A07",
            "eco": "#86D99A", "eco_soft": "rgba(134,217,154,0.14)",
            "shadow": "none",
        },
    },
    "terracotta": {
        "light": {
            "bg": "#F7F2EA", "card": "#FFFDF9", "inset": "#F0E9DE", "border": "#E4D9C9",
            "text": "#2A2019", "text2": "#655548",
            "primary": "#A94E27", "on_primary": "#FFFFFF", "primary_soft": "#F6E2D7",
            "water": "#2C6A8A", "water_soft": "#E0ECF1", "warn": "#875200", "warn_soft": "#F9ECD4",
            "danger": "#B3261E", "danger_soft": "#FAE3E0", "on_danger": "#FFFFFF",
            "eco": "#56702A", "eco_soft": "#EBF0DC",
            "shadow": "0 1px 2px rgba(42,32,25,0.06), 0 8px 22px rgba(42,32,25,0.07)",
        },
        "dark": {
            "bg": "#15110E", "card": "#201A15", "inset": "#2A231C", "border": "#3A3027",
            "text": "#F2EADF", "text2": "#B9A999",
            "primary": "#F08C5E", "on_primary": "#2A1107", "primary_soft": "rgba(240,140,94,0.15)",
            "water": "#7EC5E5", "water_soft": "rgba(126,197,229,0.15)",
            "warn": "#F2BC62", "warn_soft": "rgba(242,188,98,0.15)",
            "danger": "#FF8A7F", "danger_soft": "rgba(255,138,127,0.14)", "on_danger": "#2A0A07",
            "eco": "#B5CC7A", "eco_soft": "rgba(181,204,122,0.14)",
            "shadow": "none",
        },
    },
}


def _light_dark(light: dict[str, str], dark: dict[str, str]) -> dict[str, str]:
    """Both variants in one, resolved by CSS ``light-dark()``.

    Home Assistant publishes its dark mode as the page ``color-scheme``, so
    the cards follow it without a re-render. ``light-dark()`` takes colours
    only: a shadow keeps its light geometry with each colour switched to
    transparent in dark (every dark palette has no shadow)."""
    out = {}
    for tok, lv in light.items():
        dv = dark[tok]
        if lv == dv:
            out[tok] = lv
        elif tok == "shadow":
            assert dv == "none", tok
            out[tok] = re.sub(r"rgba\([^)]*\)", lambda m: f"light-dark({m[0]}, transparent)", lv)
        else:
            out[tok] = f"light-dark({lv}, {dv})"
    return out


for _pal in PALETTES.values():
    _pal[MODE_AUTO] = _light_dark(_pal[MODE_LIGHT], _pal[MODE_DARK])


def view_background(theme: str | None, mode: str | None) -> str | None:
    """Page colour for the views, None to keep Home Assistant's.

    The page behind the cards cannot follow a live state without extra
    cards, so it is written into the dashboard: only when both a HydroFlow
    theme and a fixed mode are chosen (the dashboard is rewritten when either
    select changes). With ``system`` or ``auto`` the page stays HA's, which
    already matches."""
    if theme not in PALETTES or theme == THEME_SYSTEM or mode not in (MODE_LIGHT, MODE_DARK):
        return None
    return PALETTES[theme][mode]["bg"]
