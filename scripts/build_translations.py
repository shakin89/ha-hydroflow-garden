"""Build every translation file from the tables below.

- strings.json and translations/{en,it}.json: what Home Assistant translates
  (config forms, entity names and states, services, issues, exceptions).
- texts/{en,it}.json: what the integration renders itself (notifications and
  the generated dashboard), see custom_components/hydroflow_garden/i18n.py.

Every config field has a label and a help text shown under the field. Edit
the tables below, then run:

    python3 scripts/build_translations.py

To add a language, add its column to every table and its code to LANGS and to
i18n.LANGUAGES. tests/test_translations.py fails when a generated file is out
of date or a language misses a key.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "hydroflow_garden"
TITLE = "HydroFlow Garden"
LANGS = ("en", "it")

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
    "dashboard_title": ("Dashboard title", "Name shown in the sidebar. Empty = 'Irrigation', translated.",
                        "Titolo dashboard", "Nome mostrato nella barra laterale. Vuoto = 'Irrigazione', tradotto."),
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


WEEKDAYS = {  # code: (EN, IT)
    "mon": ("Monday", "Lunedì"), "tue": ("Tuesday", "Martedì"), "wed": ("Wednesday", "Mercoledì"),
    "thu": ("Thursday", "Giovedì"), "fri": ("Friday", "Venerdì"), "sat": ("Saturday", "Sabato"),
    "sun": ("Sunday", "Domenica"),
}
MONTHS = {
    "jan": ("January", "Gennaio"), "feb": ("February", "Febbraio"), "mar": ("March", "Marzo"),
    "apr": ("April", "Aprile"), "may": ("May", "Maggio"), "jun": ("June", "Giugno"),
    "jul": ("July", "Luglio"), "aug": ("August", "Agosto"), "sep": ("September", "Settembre"),
    "oct": ("October", "Ottobre"), "nov": ("November", "Novembre"), "dec": ("December", "Dicembre"),
}

# Entity names by platform and translation_key: (EN, IT). {program} = "P1 Morning",
# {zone} = "Z1 Lawn". Optional states: {state: (EN, IT)}.
ENTITY = {
    "switch": {
        "system_enabled": ("System enabled", "Sistema attivo"),
        "adjust_rain": ("Cancel when raining", "Annulla se piove"),
        "logging": ("Logging", "Log attivo"),
        "notifications": ("Notifications", "Notifiche"),
        "preflight": ("Device preflight", "Preflight device"),
        "program_enabled": ("{program} enabled", "{program} attivo"),
        "program_eco": ("{program} eco", "{program} eco"),
        **{f"program_month_{c}": (f"{{program}} {en}", f"{{program}} {it}") for c, (en, it) in MONTHS.items()},
        "zone_enabled": ("{program} {zone}", "{program} {zone}"),
        **{f"zone_day_{c}": (f"{{program}} {{zone}} {en}", f"{{program}} {{zone}} {it}")
           for c, (en, it) in WEEKDAYS.items()},
    },
    "number": {
        "test_duration": ("Test duration", "Durata test"),
        "preflight_timeout": ("Preflight timeout", "Timeout preflight"),
        "fill_lead": ("Fill lead", "Anticipo riempimento"),
        "fill_duration": ("Fill duration", "Durata riempimento"),
        "si_adjust_lead": ("Smart Irrigation adjust lead", "Anticipo adjust Smart Irrigation"),
        "program_offset": ("{program} sun offset", "{program} offset sole"),
        "program_eco_cycles": ("{program} eco cycles", "{program} eco cicli"),
        "program_eco_soak": ("{program} eco soak", "{program} pausa eco"),
        "zone_duration": ("{program} {zone} duration", "{program} {zone} durata"),
    },
    "select": {
        "status_tab": ("Status tab", "Tab stato", {
            "next": ("Next", "Prossima"), "history": ("History", "Storico"),
            "smart": ("Smart", "Smart"), "timeline": ("Timeline", "Timeline")}),
        "time_type": ("{program} time type", "{program} tipo orario", {
            "fixed": ("Fixed", "Fisso"), "sunrise": ("Sunrise", "Alba"), "sunset": ("Sunset", "Tramonto")}),
    },
    "time": {
        "program_time": ("{program} time", "{program} orario"),
    },
    "sensor": {
        "suspend_reason": ("Suspension reason", "Motivo sospensione", {
            "none": ("None", "Nessuna"), "rain": ("Rain", "Pioggia"),
            "device_offline": ("Device offline", "Device offline")}),
        "zone_planned": ("{zone} planned", "{zone} Programmato"),
        "zone_today": ("{zone} today", "{zone} Oggi"),
        "zone_yesterday": ("{zone} yesterday", "{zone} Ieri"),
        "zone_two_days_ago": ("{zone} 2 days ago", "{zone} 2gg fa"),
        "rain_today": ("Rain today", "Precipitazioni oggi"),
        "rain_probability_today": ("Rain probability today", "Probabilità pioggia oggi"),
    },
    "binary_sensor": {
        "raining": ("Raining", "Sta piovendo"),
    },
    "button": {
        "test": ("Start test", "Avvia test"),
        "regenerate_dashboard": ("Regenerate dashboard", "Rigenera dashboard"),
        "write_iu_config": ("Rewrite IU config", "Riscrivi config IU"),
    },
}

EXCEPTIONS = {
    "not_loaded": ("HydroFlow Garden is not loaded", "HydroFlow Garden non è caricato"),
    "engine_off": ("The engine is off", "L'engine è spento"),
}

# Rendered by the integration (texts/<lang>.json): leaves are (EN, IT).
# Notifications take str.format placeholders.
TEXTS = {
    "notify": {
        "title": ("Irrigation", "Irrigazione"),
        "fill_offline": ("{ctrl} - P{prog} fill NOT started: device {device} offline.",
                         "{ctrl} - riempimento P{prog} NON partito: device {device} offline."),
        "preflight_suspended": (
            "{ctrl} - P{prog} {name} SUSPENDED: device {device} still offline after waiting {minutes} min. "
            "Run not started, SI buckets kept.",
            "{ctrl} - P{prog} {name} SOSPESO: device {device} ancora offline dopo {minutes} min di attesa. "
            "Corsa non avviata, bucket SI preservati."),
        "rain_skip": (
            "Irrigation skipped: {prob}% probability / {mm} mm forecast today (thresholds {prob_t}% / "
            "{mm_t} mm). Suspended for {hours} h: {names}.",
            "Skip irrigazione: {prob}% prob / {mm} mm previsti oggi (soglie {prob_t}% / {mm_t} mm). "
            "Sospesi per {hours} h: {names}."),
        "rain_detected": ("{ctrl} - Rain detected, irrigation blocked",
                          "{ctrl} - Pioggia rilevata, irrigazione bloccata"),
        "start_offline": (
            "{ctrl} - run CANCELLED: device {device} unavailable at start. No zone watered, SI buckets kept.",
            "{ctrl} - corsa ANNULLATA: device {device} non disponibile all'avvio. Nessuna zona irrigata, "
            "bucket SI preservati."),
        "run_start": ("{ctrl} - {seq} - START. Expected duration: {minutes} min",
                      "{ctrl} - {seq} - INIZIO. Durata attesa: {minutes} min"),
        "run_finish": ("{ctrl} - {seq} - FINISH. Actual duration: {minutes} min",
                       "{ctrl} - {seq} - FINE. Durata effettiva: {minutes} min"),
        "run_cancelled": ("{ctrl} - {seq} - CANCELLED", "{ctrl} - {seq} - ANNULLATO"),
    },
    "dashboard": {
        "title": ("Irrigation", "Irrigazione"),
        # JS date formatting in the status card
        "locale": ("en-GB", "it-IT"),
        "weekdays_short": (["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                           ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]),
        "months_short": (["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                         ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]),
        # status
        "status_heading": ("Irrigation status", "Stato Irrigazione"),
        "active_zone": ("Active zone", "Zona Attiva"),
        "remaining": ("remaining", "rimanenti"),
        "tab_next": ("Next", "Prossima"),
        "tab_history": ("History", "Storico"),
        "tab_smart": ("Smart", "Smart"),
        "tab_timeline": ("Timeline", "Timeline"),
        "next_title": ("Next irrigation", "Prossima Irrigazione"),
        "next_start": ("Start", "Avvio"),
        "nothing_scheduled": ("No irrigation scheduled", "Nessuna irrigazione programmata"),
        "col_zone": ("Zone", "Zona"),
        "col_when": ("When", "Quando"),
        "col_base": ("Base", "Base"),
        "col_si_estimate": ("SI estimate", "SI stima"),
        "col_iu_now": ("IU now", "IU ora"),
        "next_legend": (
            "**Base** = helper duration of the starting program.\n"
            "**SI estimate** = what the adjust will write (SI ÷ cycles), updated live.\n"
            "**IU now** = what IU has planned right now: it matches SI estimate\n"
            "only after the adjust has run (5 min before the start).",
            "**Base** = durata helper del programma in partenza.\n"
            "**SI stima** = quanto scriverà l'adjust (SI ÷ cicli), aggiornato live.\n"
            "**IU ora** = quanto IU ha in programma adesso: coincide con SI stima\n"
            "solo dopo che l'adjust è girato (5 min prima dell'avvio)."),
        "history_title": ("Irrigation history", "Storico Irrigazione"),
        "col_today": ("Today", "Oggi"),
        "col_yesterday": ("Yesterday", "Ieri"),
        "col_two_days_ago": ("2 days ago", "2gg fa"),
        "smart_title": ("Smart Irrigation", "Smart Irrigation"),
        "smart_intro": (
            "Current water deficit and the volume SI would deliver **with the bucket\n"
            "as it is now**, without waiting for the adjust.",
            "Deficit idrico corrente e volume che SI erogherebbe **col bucket\n"
            "di adesso**, senza aspettare l'adjust."),
        "col_bucket": ("Bucket", "Bucket"),
        "col_duration": ("Duration", "Durata"),
        "col_liters": ("Liters", "Litri"),
        "col_mm": ("mm", "mm"),
        "calibration": ("**Zone calibration** — `s/mm = multiplier × size / throughput × 60`",
                        "**Calibrazione zona** — `s/mm = multiplier × size / portata × 60`"),
        "col_size": ("Size", "Size"),
        "col_throughput": ("Throughput", "Portata"),
        "col_s_per_mm": ("s/mm", "s/mm"),
        "col_at_2mm": ("at 2mm", "a 2mm"),
        "calibration_note": (
            "_s/mm and \"at 2mm\" are 0 right after a bucket reset: they need\n"
            "accumulated ET data._",
            "_s/mm e \"a 2mm\" valgono 0 subito dopo un reset bucket: servono\n"
            "dati ET accumulati per calcolarli._"),
        "last_si_calc": ("Last SI calculation", "Ultimo calcolo SI"),
        "si_hourly": ("recalculated automatically every hour at minute 10",
                      "ricalcolo automatico ogni ora al minuto 10"),
        "never": ("never", "mai"),
        "timeline_title": ("Watering timeline", "Cronologia irrigazione"),
        "today": ("Today", "Oggi"),
        "minutes": ("minutes", "minuti"),
        # programs
        "programs_heading": ("Programs", "Programmi"),
        "program": ("Program", "Programma"),
        "time_heading": ("Start time", "Orario"),
        "time_type": ("Time type", "Tipo di orario"),
        "offset": ("Offset", "Offset"),
        "months_heading": ("Months", "Mesi dell'anno"),
        "eco_heading": ("ECO mode", "Modalità ECO"),
        "zones_heading": ("Zones", "Zone"),
        "eco_mode": ("Eco mode", "Modalità eco"),
        "cycles": ("Cycles", "Cicli"),
        "soak": ("Soak", "Pausa"),
        "zone": ("Zone", "Zona"),
        "effective": ("Eff.", "Eff."),
        "all_days": ("All", "Tutti"),
        # system
        "system_heading": ("System", "Sistema"),
        "irrigation_system": ("Irrigation system", "Sistema irrigazione"),
        "system": ("System", "Sistema"),
        "on": ("On", "Attivo"),
        "off": ("Off", "Spento"),
        "fill": ("Fill", "Riempimento"),
        "rain_block": ("Rain block", "Comp. Pioggia"),
        "reset_buckets": ("Reset all buckets", "Azzera tutti i bucket"),
        "reset_buckets_confirm": ("Reset all SI buckets of {ctrl}?", "Azzerare tutti i bucket SI di {ctrl}?"),
        "logging": ("Logging", "Logging"),
        "notifications": ("Notifications", "Notifiche"),
        "preflight_device": ("Device preflight", "Preflight device"),
        "preflight_timeout": ("Preflight timeout", "Timeout Preflight"),
        "fill_lead": ("Fill lead", "Anticipo Riempimento"),
        "fill_duration": ("Fill duration", "Durata Riempimento"),
        # controller status card
        "device_offline": ("Device offline", "Device offline"),
        "unreachable": ("Unreachable - irrigation blocked", "Non raggiungibile - irrigazione bloccata"),
        "suspended": ("Suspended", "Sospeso"),
        # suspension reason code -> text shown in brackets
        "reasons": {"rain": ("rain", "pioggia"), "device_offline": ("device offline", "device offline")},
        "resumes_at": ("Resumes at", "Riprende alle"),
        "resumes_on": ("Resumes on", "Riprende il"),
        "at": ("at", "alle"),
        "watering": ("Watering", "Irrigando"),
        "running": ("Running", "In corso"),
        "idle": ("Idle", "Inattivo"),
        "raining_blocked": ("Raining - irrigation blocked", "Piove - Irrigazione Bloccata"),
        "raining_ignored": ("Raining - block ignored", "Piove - Blocco Ignorato"),
        "rain_ok": ("Rain sensor - OK", "Sensore Pioggia - OK"),
    },
}


def _fields(table, lang):
    i = 0 if lang == "en" else 2
    return ({k: v[i] for k, v in table.items()}, {k: v[i + 1] for k, v in table.items()})


def _sel(table, lang):
    i = 0 if lang == "en" else 2
    return {"fields": {k: {"name": v[i], "description": v[i + 1]} for k, v in table.items()}}


def _pick(node, i):
    """Leaves are (EN, IT) tuples; dicts recurse."""
    if isinstance(node, dict):
        return {k: _pick(v, i) for k, v in node.items()}
    return node[i]


def _entity(lang):
    i = LANGS.index(lang)
    out = {}
    for platform, items in ENTITY.items():
        out[platform] = {}
        for key, row in items.items():
            item = {"name": row[i]}
            if len(row) > 2:
                item["state"] = {code: labels[i] for code, labels in row[2].items()}
            out[platform][key] = item
    return out


def build_texts(lang: str) -> dict:
    return _pick(TEXTS, LANGS.index(lang))


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
        "entity": _entity(lang),
        "exceptions": {k: {"message": v[LANGS.index(lang)]} for k, v in EXCEPTIONS.items()},
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


def outputs() -> dict[Path, dict]:
    """Every generated file and its content."""
    files = {ROOT / "strings.json": build("en")}
    for lang in LANGS:
        files[ROOT / "translations" / f"{lang}.json"] = build(lang)
        files[ROOT / "texts" / f"{lang}.json"] = build_texts(lang)
    return files


def render(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    for path, data in outputs().items():
        path.parent.mkdir(exist_ok=True)
        path.write_text(render(data), encoding="utf-8")


if __name__ == "__main__":
    main()
