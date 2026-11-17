"""Irrigation event log: plain text lines, size-based rotation.

Written directly by the integration (no File notify entity, no shell
command). Lines keep the format of the YAML era so old and new logs read the
same, e.g.::

    2026-04-11T12:00:00 [valve_on] ctrl=Garden zone=Z1 Lawn entity=switch.v1 duration=600s
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def format_line(
    event: str,
    controller: str,
    zone: str = "ALL",
    duration: object | None = 0,
    sequence: str = "",
    entity: str = "",
    run_type: str = "",
) -> str:
    ts = dt_util.now().strftime("%Y-%m-%dT%H:%M:%S")
    seq = f" seq={sequence}" if sequence and sequence != "none" else ""
    ent = f" entity={entity}" if entity else ""
    typ = f" type={run_type}" if run_type else ""
    dur = "" if duration is None else f" duration={duration}s"  # None: no duration (markers)
    return f"{ts} [{event}] ctrl={controller}{seq} zone={zone}{ent}{dur}{typ}"


class LogFile:
    def __init__(self, hass: HomeAssistant, path: str, max_mb: float, keep: int) -> None:
        self.hass = hass
        p = Path(path)
        self.path = p if p.is_absolute() else Path(hass.config.path(path))
        self.max_bytes = int(max_mb * 1024 * 1024)
        self.keep = max(int(keep), 0)

    def _rotate(self) -> None:
        if self.keep == 0:
            self.path.write_text("", encoding="utf-8")
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.keep}")
        if oldest.exists():
            oldest.unlink()
        for n in range(self.keep - 1, 0, -1):
            src = self.path.with_name(f"{self.path.name}.{n}")
            if src.exists():
                src.rename(self.path.with_name(f"{self.path.name}.{n + 1}"))
        self.path.rename(self.path.with_name(f"{self.path.name}.1"))

    def _write(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.max_bytes and self.path.exists() and self.path.stat().st_size >= self.max_bytes:
            self._rotate()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    async def async_write(self, line: str) -> None:
        try:
            await self.hass.async_add_executor_job(self._write, line)
        except OSError as err:
            _LOGGER.warning("Cannot write %s: %s", self.path, err)
