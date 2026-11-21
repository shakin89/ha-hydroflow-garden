"""Persistent store of the user-adjustable values, with change listeners.

The entities are views on this store; the engine and the IU writer read it.
Keeping the values here (not in each entity's restore state) gives one place
to read them synchronously and one file to persist.

Seeding: a key with no stored value takes the state of the YAML helper with
the same object_id (``input_boolean.<key>`` ...), as left by the generator
this integration replaces; failing that, the spec default.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, LEGACY_OPTIONS
from .model import KIND_NUMBER, KIND_SELECT, KIND_SWITCH, KIND_TIME, ValueSpec

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY = 2

Listener = Callable[[str, Any], None]


def _from_legacy(spec: ValueSpec, state: str) -> Any:
    """Convert a legacy helper state to a typed value, None if unusable."""
    if state in (None, "", "unknown", "unavailable"):
        return None
    try:
        if spec.kind == KIND_SWITCH:
            return {"on": True, "off": False}.get(state)
        if spec.kind == KIND_NUMBER:
            return max(spec.min, min(spec.max, float(state)))
        if spec.kind == KIND_TIME:
            parts = state.split(":")
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]) if len(parts) > 2 else 0:02d}"
        if spec.kind == KIND_SELECT:
            state = LEGACY_OPTIONS.get(state, state)
            return state if state in spec.options else None
    except (TypeError, ValueError, IndexError):
        return None
    return None


class ValueStore:
    """Typed values by key; listeners per key and global."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.values"
        )
        self._data: dict[str, Any] = {}
        self._key_listeners: dict[str, list[Listener]] = {}
        self._listeners: list[Listener] = []

    async def async_load(
        self, specs: dict[str, ValueSpec], extra: dict[str, Any], seed: dict[str, Any] | None = None
    ) -> list[str]:
        """Load, seed missing keys. Returns the keys seeded.

        Seed order: ``seed`` (values given with the YAML import), then the
        legacy helper with the same object_id, then the spec default."""
        seed = seed or {}
        self._data = (await self._store.async_load()) or {}
        seeded: list[str] = []
        changed = self._migrate_options(specs, extra)
        for key, spec in specs.items():
            if key in self._data:
                continue
            value = None
            if key in seed:
                raw = seed[key]
                if isinstance(raw, bool):
                    raw = "on" if raw else "off"
                value = _from_legacy(spec, str(raw))
                if value is not None:
                    seeded.append(key)
            if value is None and spec.legacy_domain:
                state = self.hass.states.get(f"{spec.legacy_domain}.{key}")
                if state is not None:
                    value = _from_legacy(spec, state.state)
                    if value is not None:
                        seeded.append(key)
            self._data[key] = spec.default if value is None else value
            changed = True
        for key, default in extra.items():
            if key not in self._data:
                self._data[key] = default
                changed = True
        if changed:
            self._store.async_delay_save(lambda: self._data, SAVE_DELAY)
        return seeded

    def _migrate_options(self, specs: dict[str, ValueSpec], extra: dict[str, Any]) -> bool:
        """Stored Italian option labels (before 0.3) -> language-neutral codes."""
        keys = {k for k, s in specs.items() if s.kind == KIND_SELECT} | set(extra)
        changed = False
        for key in keys:
            old = self._data.get(key)
            if isinstance(old, str) and old in LEGACY_OPTIONS:
                self._data[key] = LEGACY_OPTIONS[old]
                changed = True
        return changed

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        """A copy of every stored value."""
        return dict(self._data)

    @callback
    def set(self, key: str, value: Any) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)
        for cb in list(self._key_listeners.get(key, ())):
            cb(key, value)
        for cb in list(self._listeners):
            cb(key, value)

    @callback
    def listen(self, cb: Listener, key: str | None = None) -> Callable[[], None]:
        target = self._listeners if key is None else self._key_listeners.setdefault(key, [])
        target.append(cb)

        @callback
        def _remove() -> None:
            if cb in target:
                target.remove(cb)

        return _remove

    async def async_flush(self) -> None:
        await self._store.async_save(self._data)

    async def async_remove(self) -> None:
        await self._store.async_remove()
