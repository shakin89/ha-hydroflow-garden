"""Reference copy of the YAML generator's IU builder (pre-integration).

Verbatim functions from generate_irrigation.py, kept only to pin the
behaviour of iu_config.py in test_iu_config_parity.py. Do not edit.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

WEEKDAYS = [(d, d, d) for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]
MONTHS = [(m, m, m) for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")]
HEADER = "# reference\n"


@dataclass
class Zone:
    id: int
    name: str
    entity_id: str
    smart_irrigation: bool = True


@dataclass
class Program:
    id: int
    name: str
    default_time: str = "06:00"


@dataclass
class Controller:
    id: str
    name: str
    iu_controller_id: str
    entity_id: str
    max_zone_duration: str
    zones: list = field(default_factory=list)
    programs: list = field(default_factory=list)
    iu_index: int = 0


def _eid(ctrl: str, *parts: str) -> str:
    return "iu_" + "_".join([ctrl] + list(parts))


def _get_state(states: dict[str, str], entity_id: str, default: str = "") -> str:
    """Legge uno stato dal dizionario, con default."""
    return states.get(entity_id, default)


def _fmt_duration(seconds: int) -> str:
    """Formatta secondi in HH:MM:SS per IU."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _resolve_time(states: dict[str, str] | None, ctrl_id: str, prog: Program) -> dict:
    """Risolve il campo time per uno schedule IU.

    Ritorna un dict che rappresenta il campo time in formato IU:
    - Fisso: {"time": "06:00"}
    - Alba:  {"time": {"sun": "sunrise", "after": "00:30"}} oppure {"time": {"sun": "sunrise", "before": "00:30"}}
    - Tramonto: analogo con "sunset"
    """
    pn = f"p{prog.id}"
    if states is None:
        # Nessuno stato disponibile → usa default
        return {"value": prog.default_time, "type": "fixed"}

    time_type = _get_state(states, f"input_select.{_eid(ctrl_id, pn, 'time_type')}", "Fisso")
    fixed_time = _get_state(states, f"input_datetime.{_eid(ctrl_id, pn, 'time')}", prog.default_time)
    offset = int(float(_get_state(states, f"input_number.{_eid(ctrl_id, pn, 'offset')}", "0")))

    if time_type == "Fisso":
        # input_datetime restituisce "HH:MM:SS" o "HH:MM"
        t = fixed_time[:5] if len(fixed_time) > 5 else fixed_time
        return {"value": t, "type": "fixed"}
    elif time_type == "Alba":
        return {"value": "sunrise", "offset": offset, "type": "sun"}
    elif time_type == "Tramonto":
        return {"value": "sunset", "offset": offset, "type": "sun"}
    return {"value": prog.default_time, "type": "fixed"}


def _build_iu_context(controllers: list[Controller],
                      states: dict[str, str] | None) -> dict:
    """Costruisce il context dict per il template irrigation_unlimited.yaml.j2.

    Tutta la logica (lettura stati, pattern matching giorni→sequence,
    slot allocation sequence_id, default values) vive qui. Il template
    si limita alla formattazione YAML.
    """
    ctrl_dicts: list[dict] = []

    for ctrl in controllers:
        c = ctrl.id
        n_zones = len(ctrl.zones)

        # Controller enabled
        sys_enabled = True
        if states:
            sys_enabled = _get_state(states, f"input_boolean.{_eid(c, 'system_enabled')}", "on") == "on"

        sequences: list[dict] = []

        for p in ctrl.programs:
            pn = f"p{p.id}"

            # Program enabled
            prog_enabled = True
            if states:
                prog_enabled = _get_state(states, f"input_boolean.{_eid(c, pn, 'enabled')}", "on") == "on"

            # Eco mode
            eco_on = False
            eco_cycles = 1
            eco_soak_secs = 0
            if states:
                eco_on = _get_state(states, f"input_boolean.{_eid(c, pn, 'eco')}", "off") == "on"
                eco_cycles = int(float(_get_state(states, f"input_number.{_eid(c, pn, 'eco_cycles')}", "2")))
                # eco_soak è ora in secondi (può essere negativo per overlap tra cicli)
                eco_soak_secs = int(float(_get_state(states, f"input_number.{_eid(c, pn, 'eco_soak')}", "600")))

            # IU repeat = ripetizioni EXTRA (repeat:1 = 2 esecuzioni totali)
            # L'utente imposta "cicli" = esecuzioni totali, quindi -1.
            # Le durate zona vengono divise per eco_cycles (l'utente imposta
            # il tempo TOTALE di irrigazione, il programma lo fraziona).
            repeat = max(eco_cycles, 1) if eco_on else 1
            # Delay in secondi interi: IU accetta formato numerico e supporta valori negativi
            soak_secs = eco_soak_secs if eco_on else 0

            # Schedule (orario + mesi sono per-programma)
            time_info = _resolve_time(states, c, p)

            if states:
                active_months = [
                    mc for mc, _, _ in MONTHS
                    if _get_state(states, f"input_boolean.{_eid(c, pn, mc)}", "off") == "on"
                ]
            else:
                active_months = ["apr", "may", "jun", "jul", "aug", "sep"]

            # Giorni per zona; poi raggruppati per insieme di zone (vedi sotto)
            zone_days: dict[int, tuple] = {}
            zone_durations: dict[int, int] = {}

            for z in ctrl.zones:
                if states:
                    zone_enabled = _get_state(
                        states, f"input_boolean.{_eid(c, pn, f'z{z.id}_enabled')}", "off"
                    ) == "on"
                else:
                    zone_enabled = (p.id == 1)

                if not zone_enabled:
                    continue

                if states:
                    days = tuple(
                        day_code for day_code, _, _ in WEEKDAYS
                        if _get_state(
                            states, f"input_boolean.{_eid(c, pn, f'z{z.id}_{day_code}')}", "off"
                        ) == "on"
                    )
                else:
                    days = ("mon", "wed", "fri")

                if not days:
                    continue

                if states:
                    dur_min = int(float(_get_state(
                        states, f"input_number.{_eid(c, pn, f'z{z.id}_duration')}", "10"
                    )))
                else:
                    dur_min = 10
                # Eco mode: la durata impostata è il totale, dividi per cicli.
                # Lavoriamo in secondi per non perdere precisione.
                dur_secs = dur_min * 60
                if eco_on and eco_cycles > 1:
                    dur_secs = max(dur_secs // eco_cycles, 1)
                zone_durations[z.id] = dur_secs
                zone_days[z.id] = days

            # Una sequence per insieme di zone, con i giorni in cui gira
            # esattamente quell'insieme. Ogni giorno cade in UNA sola sequence:
            # sequence diverse dello stesso programma hanno lo stesso orario,
            # quindi se condividessero un giorno IU le farebbe partire in
            # parallelo (zone aperte insieme). Raggruppare zone per pattern di
            # giorni violava questo vincolo (es. Z1 lun/mer/ven + Z3 lun/ven).
            zones_to_days: dict[tuple, list[str]] = {}
            for day_code, _, _ in WEEKDAYS:
                day_zones = tuple(z.id for z in ctrl.zones if day_code in zone_days.get(z.id, ()))
                if day_zones:
                    zones_to_days.setdefault(day_zones, []).append(day_code)

            # Slot allocation: P{N} → slot_base = (N-1)*n_zones+1
            slot_base = (p.id - 1) * n_zones + 1

            for idx, (day_zones, pattern) in enumerate(zones_to_days.items()):
                if idx >= n_zones:
                    print(f"WARNING: {c} P{p.id}: {len(zones_to_days)} combinazioni "
                          f"zone/giorni > {n_zones} slot, giorni {pattern} ignorati",
                          file=sys.stderr)
                    continue
                sequences.append({
                    "sequence_id": slot_base + idx,
                    "name": f"P{p.id} {p.name} #{idx + 1}",
                    "enabled": prog_enabled,
                    "repeat": repeat,
                    "delay": soak_secs,
                    "schedule_name": f"Schedule P{p.id} #{idx + 1}",
                    "time": time_info,
                    "weekday": list(pattern),
                    "months": active_months,
                    "zones": [
                        {"id": zid, "duration": _fmt_duration(zone_durations[zid])}
                        for zid in day_zones
                    ],
                })

        ctrl_dicts.append({
            "name": ctrl.name,
            "controller_id": ctrl.iu_controller_id,
            "enabled": sys_enabled,
            "entity_id": ctrl.entity_id,
            "max_zone_duration": ctrl.max_zone_duration,
            "zones": [
                {"id": z.id, "name": z.name, "entity_id": z.entity_id,
                 "smart_irrigation": z.smart_irrigation}
                for z in ctrl.zones
            ],
            "sequences": sequences,
        })

    return {"controllers": ctrl_dicts, "header": HEADER.rstrip()}
