"""Build strings.json and translations/{en,it}.json from one table.

Every config field has a label and a help text shown under the field. Edit
the tables below, then run:

    python3 scripts/build_translations.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "hydroflow_garden"
TITLE = "HydroFlow Garden"

# key: (label EN, help EN, label IT, help IT)
HUB = {
    "engine_enabled": (
        "Engine active",
        "Off: entities only, nothing is written or triggered (useful while migrating). On: writes the "
        "Irrigation Unlimited file and runs fill, preflight, Smart Irrigation, rain skip, log and notifications.",
        "Engine attivo",
        "Spento: solo entità, niente viene scritto o eseguito (utile durante la migrazione). Acceso: scrive il "
        "file di Irrigation Unlimited ed esegue riempimento, preflight, Smart Irrigation, skip pioggia, log e notifiche.",
    ),
    "notify_entities": (
        "Notify entities",
        "Entities called with notify.send_message (e.g. a Telegram bot). Leave empty for none.",
        "Entità notify",
        "Entità chiamate con notify.send_message (es. un bot Telegram). Vuoto = nessuna.",
    ),
    "notify_services": (
        "Legacy notify services",
        "Full service names, one per line, e.g. notify.mobile_app_my_phone.",
        "Servizi notify legacy",
        "Nomi completi dei servizi, uno per riga, es. notify.mobile_app_telefono.",
    ),
    "notify_persistent": (
        "Persistent notifications",
        "Also show every message as a persistent notification in Home Assistant.",
        "Notifiche persistenti",
        "Mostra ogni messaggio anche come notifica persistente in Home Assistant.",
    ),
    "weather_entity": (
        "Weather entity",
        "Must provide daily forecasts with precipitation (mm) and precipitation_probability (%). Enables "
        "the daily rain skip and the forecast sensors.",
        "Entità meteo",
        "Deve fornire previsioni giornaliere con precipitazione (mm) e probabilità (%). Abilita lo skip "
        "pioggia giornaliero e i sensori di previsione.",
    ),
    "rain_now_entity": (
        "Raining-now entity",
        "Any entity telling that it is raining right now (rain sensor, weather station, forecast condition). "
        "A scheduled run that starts while it rains is cancelled.",
        "Entità pioggia in corso",
        "Qualsiasi entità che dica che sta piovendo adesso (sensore pioggia, stazione meteo, condizione meteo). "
        "Una corsa schedulata che parte mentre piove viene annullata.",
    ),
    "rain_now_state": (
        "Raining state",
        "State of that entity meaning rain: 'on' for a binary sensor, e.g. 'rain' for a weather condition.",
        "Stato che indica pioggia",
        "Stato di quell'entità che significa pioggia: 'on' per un binary sensor, es. 'rain' per una condizione meteo.",
    ),
    "prob_threshold": (
        "Skip at probability",
        "The day is skipped when today's rain probability is at least this value...",
        "Salta con probabilità",
        "La giornata viene saltata se la probabilità di pioggia di oggi è almeno questo valore...",
    ),
    "mm_threshold": (
        "...and at rain",
        "...and the forecast rain is at least this many mm. Both conditions are required.",
        "...e con pioggia",
        "...e la pioggia prevista è almeno questi mm. Servono entrambe le condizioni.",
    ),
    "skip_time": (
        "Forecast check time",
        "When the forecast is checked every day. Put it before your earliest program.",
        "Ora controllo previsione",
        "Quando viene controllata la previsione ogni giorno. Mettila prima del programma più mattutino.",
    ),
    "skip_hours": (
        "Suspension length",
        "Hours the active controllers stay suspended after a rain skip.",
        "Durata sospensione",
        "Ore di sospensione dei controller attivi dopo uno skip pioggia.",
    ),
    "log_path": (
        "Event log file",
        "Plain text log of starts, finishes, valves and faults. Relative paths are inside the config folder.",
        "File di log eventi",
        "Log testuale di avvii, fine corse, valvole e guasti. I percorsi relativi sono nella cartella config.",
    ),
    "log_max_mb": ("Rotate log above", "Size that triggers a rotation.",
                   "Ruota il log oltre", "Dimensione oltre la quale il log viene ruotato."),
    "log_keep": ("Rotated copies", "How many old copies (.1, .2, ...) are kept.",
                 "Copie ruotate", "Quante copie vecchie (.1, .2, ...) vengono tenute."),
    "iu_config_path": (
        "Irrigation Unlimited file",
        "The file configuration.yaml includes with `irrigation_unlimited: !include` (this file name). It is "
        "overwritten by this integration.",
        "File di Irrigation Unlimited",
        "Il file incluso da configuration.yaml con `irrigation_unlimited: !include` (this file name). Viene "
        "sovrascritto da questa integrazione.",
    ),
    "dashboard_url": (
        "Dashboard URL",
        "Path of the generated dashboard. Must contain a dash, e.g. hydroflow-garden.",
        "URL dashboard",
        "Percorso della dashboard generata. Deve contenere un trattino, es. hydroflow-garden.",
    ),
    "dashboard_title": ("Dashboard title", "Name shown in the sidebar.",
                        "Titolo dashboard", "Nome mostrato nella barra laterale."),
}

CONTROLLER = {
    "name": (
        "Name",
        "Shown in the dashboard and in notifications, e.g. Garden.",
        "Nome",
        "Mostrato nella dashboard e nelle notifiche, es. Giardino.",
    ),
    "id": (
        "Id",
        "Short slug used in every entity id (switch.iu_ID_...). Cannot change later. Empty = from the name.",
        "Id",
        "Slug breve usato in ogni entity id (switch.iu_ID_...). Non si cambia dopo. Vuoto = dal nome.",
    ),
    "iu_controller_id": (
        "IU controller_id",
        "controller_id written in the Irrigation Unlimited file. Empty = from the name.",
        "controller_id IU",
        "controller_id scritto nel file di Irrigation Unlimited. Vuoto = dal nome.",
    ),
    "entity_id": (
        "Pump / master valve",
        "Switch turned on by Irrigation Unlimited whenever any zone of this controller waters.",
        "Pompa / valvola master",
        "Switch acceso da Irrigation Unlimited ogni volta che una zona di questo controller irriga.",
    ),
    "max_zone_duration": (
        "Max zone run",
        "Safety cap for one zone run, HH:MM (Irrigation Unlimited `maximum`).",
        "Durata massima zona",
        "Limite di sicurezza per una corsa di zona, HH:MM (`maximum` di Irrigation Unlimited).",
    ),
    "zones": (
        "Zones",
        "One row per valve: id (fixed, part of the entity ids), name, valve switch and optionally the "
        "Smart Irrigation sensor that gives its duration.",
        "Zone",
        "Una riga per valvola: id (fisso, entra negli entity id), nome, switch della valvola e, se c'è, il "
        "sensore Smart Irrigation che ne calcola la durata.",
    ),
    "programs": (
        "Programs",
        "One row per daily start (up to 9): id, name, default time. Each program has its own time, months, "
        "eco and per-zone weekdays and durations.",
        "Programmi",
        "Una riga per ogni partenza giornaliera (fino a 9): id, nome, orario predefinito. Ogni programma ha "
        "orario, mesi, eco e giorni/durate per zona propri.",
    ),
    "fill_switches": (
        "Cistern fill switches",
        "Optional: switches turned on before each program to fill a tank. Empty = no fill.",
        "Switch riempimento cisterna",
        "Facoltativo: switch accesi prima di ogni programma per riempire una cisterna. Vuoto = nessun riempimento.",
    ),
    "fill_lead_minutes": (
        "Fill lead",
        "Default minutes before the program start when filling begins (adjustable later from the dashboard).",
        "Anticipo riempimento",
        "Minuti predefiniti prima dell'avvio del programma in cui parte il riempimento (modificabile poi in dashboard).",
    ),
    "fill_duration_minutes": (
        "Fill duration",
        "Default minutes the fill switches stay on.",
        "Durata riempimento",
        "Minuti predefiniti per cui gli switch di riempimento restano accesi.",
    ),
    "availability_entity": (
        "Valve device connectivity",
        "Optional binary_sensor that is 'on' when the valve controller (e.g. ESPHome status) is online. "
        "Enables the preflight: wait, suspend or cancel a run with the device offline, and no Smart "
        "Irrigation bucket reset for water never delivered.",
        "Connettività device valvole",
        "Binary_sensor facoltativo, 'on' quando il controller delle valvole (es. status ESPHome) è online. "
        "Abilita il preflight: attende, sospende o annulla una corsa a device offline e non azzera i bucket "
        "Smart Irrigation per acqua mai erogata.",
    ),
    "preflight_timeout_minutes": (
        "Preflight wait",
        "Default minutes before the start at which the device is checked and waited for.",
        "Attesa preflight",
        "Minuti predefiniti prima dell'avvio in cui il device viene controllato e atteso.",
    ),
}

ZONE_FIELDS = {
    "id": ("Zone id", "Number, fixed: changing it creates a new zone.",
           "Id zona", "Numero, fisso: cambiarlo crea una zona nuova."),
    "name": ("Name", "e.g. Lawn.", "Nome", "es. Prato."),
    "entity_id": ("Valve", "Switch or valve that opens this zone.",
                  "Valvola", "Switch o valve che apre questa zona."),
    "si_sensor": ("Smart Irrigation sensor", "Optional: its value becomes the zone duration before each run.",
                  "Sensore Smart Irrigation", "Facoltativo: il suo valore diventa la durata della zona prima di ogni corsa."),
}
PROGRAM_FIELDS = {
    "id": ("Program id", "1 to 9, fixed.", "Id programma", "Da 1 a 9, fisso."),
    "name": ("Name", "e.g. Morning.", "Nome", "es. Mattina."),
    "default_time": ("Default time", "Initial start time; change it later from the dashboard.",
                     "Orario predefinito", "Orario iniziale; si cambia poi dalla dashboard."),
}


def _fields(table, lang):
    i = 0 if lang == "en" else 2
    return ({k: v[i] for k, v in table.items()}, {k: v[i + 1] for k, v in table.items()})


def _sel(table, lang):
    i = 0 if lang == "en" else 2
    return {"fields": {k: {"name": v[i], "description": v[i + 1]} for k, v in table.items()}}


def build(lang: str) -> dict:
    it = lang == "it"
    hub_d, hub_h = _fields(HUB, lang)
    c_d, c_h = _fields(CONTROLLER, lang)
    recon_d = {k: v for k, v in c_d.items() if k != "id"}
    recon_h = {k: v for k, v in c_h.items() if k != "id"}
    sub_desc = (
        "Un controller = un impianto con la sua pompa e le sue valvole (un controller di Irrigation Unlimited). "
        "Zone e programmi sono identificati dal loro id: cambiare un id crea una zona/programma nuovo."
        if it else
        "A controller = one system with its pump and valves (one Irrigation Unlimited controller). "
        "Zones and programs are identified by their id: changing an id makes a new zone/program."
    )
    hub_desc = (
        "Impostazioni comuni a tutti i controller. I controller si aggiungono dopo, con \"Aggiungi controller\"."
        if it else
        "Settings shared by all controllers. Add controllers afterwards with \"Add controller\"."
    )
    errs = {
        "no_zones": "Aggiungi almeno una zona" if it else "Add at least one zone",
        "no_programs": "Aggiungi almeno un programma" if it else "Add at least one program",
        "duplicate_id": "Id duplicato" if it else "Duplicate id",
        "already_configured": "Esiste già un controller con questo id" if it else "A controller with this id exists",
    }
    return {
        "config": {
            "step": {"user": {"title": TITLE, "description": hub_desc,
                              "data": hub_d, "data_description": hub_h}},
            "abort": {"already_configured": "Già configurato" if it else "Already configured",
                      "single_instance_allowed": "Già configurato" if it else "Already configured"},
        },
        "options": {"step": {"init": {"title": TITLE, "description": hub_desc,
                                      "data": hub_d, "data_description": hub_h}}},
        "config_subentries": {"controller": {
            "initiate_flow": {"user": "Aggiungi controller" if it else "Add controller"},
            "entry_type": "Controller",
            "step": {
                "user": {"title": "Nuovo controller" if it else "New controller", "description": sub_desc,
                         "data": c_d, "data_description": c_h},
                "reconfigure": {"title": "Controller", "description": sub_desc,
                                "data": recon_d, "data_description": recon_h},
            },
            "error": errs,
            "abort": {"reconfigure_successful": "Salvato" if it else "Saved"},
        }},
        "selector": {"zones": _sel(ZONE_FIELDS, lang), "programs": _sel(PROGRAM_FIELDS, lang)},
        "issues": {"missing_cards": {
            "title": "Card mancanti per la dashboard irrigazione" if it else "Cards missing for the irrigation dashboard",
            "description": ("Installa dal Marketplace/HACS: {cards}. Senza, la dashboard generata non si vede."
                            if it else "Install from the Marketplace/HACS: {cards}. Without them the generated "
                            "dashboard does not render."),
        }},
        "services": {
            "regenerate_dashboard": {
                "name": "Rigenera dashboard" if it else "Regenerate dashboard",
                "description": "Riscrive la dashboard irrigazione dai template." if it
                else "Rewrite the irrigation dashboard from the templates."},
            "write_iu_config": {
                "name": "Scrivi config IU" if it else "Write IU config",
                "description": "Riscrive irrigation_unlimited.yaml e ricarica IU." if it
                else "Rewrite irrigation_unlimited.yaml and reload IU."},
            "rain_skip": {
                "name": "Controllo pioggia" if it else "Rain check",
                "description": "Esegue ora il controllo previsione pioggia." if it
                else "Run the rain forecast check now.",
                "fields": {"force": {
                    "name": "Forza" if it else "Force",
                    "description": "Sospende anche sotto soglia (test)." if it
                    else "Suspend even below the thresholds (test)."}}},
        },
    }


def main() -> None:
    en, it = build("en"), build("it")
    for path, data in ((ROOT / "strings.json", en), (ROOT / "translations" / "en.json", en),
                       (ROOT / "translations" / "it.json", it)):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
