# Note di progetto

<img src="https://raw.githubusercontent.com/shakin89/ha-hydroflow-garden/main/docs/images/flag-gb.svg" width="18" alt="EN"> [Read in English](CONTEXT.md)

Decisioni che il codice da solo non spiega. Questa integrazione sostituisce uno
script Python che generava pacchetti YAML. Il suo comportamento è fissato da
`tests/test_iu_config_parity.py`, che gira contro una copia letterale del
builder di quello script.

## Le chiavi dei valori sono gli object_id delle entità

`model.eid()` costruisce le chiavi come `iu_<controller>_<parti>`. Una chiave è
l'object_id e lo unique_id dell'entità del valore. È anche il modo in cui il
valore viene inizializzato dall'helper YAML con lo stesso object_id. Cambiare il
formato rompe tutte e tre le cose. L'id di una zona o di un programma fa parte
delle sue chiavi, quindi cambiare un id crea una nuova zona.

I sensori per zona (`..._programmato`, `..._oggi`) prendono l'object_id dal
**nome** della zona, come facevano i sensori YAML. Rinominare una zona crea
quindi nuovi sensori. I suffissi di questi object_id sono in italiano (`_programmato`,
`_oggi`, `_ieri`, `_2gg_fa`) in ogni lingua: vengono tradotti solo i nomi.

## Traduzioni

Home Assistant traduce ciò che mostra lui: nomi delle entità (translation_key
più placeholder come `{program}`), opzioni dei select e stati dei sensori enum,
form, servizi, avvisi ed eccezioni. Notifiche e dashboard le genera
l'integrazione, quindi i loro testi stanno in `texts/<lingua>.json`, scelto in
base alla lingua di HA (inglese come ripiego). Un cambio di lingua ricarica
l'entry, e questo rigenera anche la dashboard. Tutti i file sono generati da
`scripts/build_translations.py`, e un test fallisce se uno non è aggiornato.

I valori salvati delle opzioni e gli stati enum sono codici (`fixed`, `rain`,
`next`...). Prima della 0.3 erano etichette in italiano. Il value store li
converte al caricamento, e lo stesso fa il seeding dai vecchi helper
`input_select`, tramite `LEGACY_OPTIONS`.

## Gli indici di IU sono posizionali

IU chiama le sue entità `c<N>_m`, `c<N>_z<M>` e `c<N>_s<M>` in base alla
**posizione** nel suo YAML. Per le sequenze la posizione non è il
`sequence_id`. I controller sono ordinati dal campo `order`, assegnato una sola
volta alla creazione del controller. Le entità di IU vengono cercate nel
registro entità tramite unique_id. Mai scrivere `_s<M>` a mano. Un programma ha
più sequenze, e le loro posizioni cambiano ogni volta che cambiano i giorni.

## IU si configura a runtime, mai da file

Un'integrazione non deve scrivere YAML nella cartella di configurazione.
L'utente incolla una volta una struttura statica (`iu_config.build_structure`):
ogni programma ha fino a 7 sequenze (slot: una per insieme distinto di zone, e
ogni giorno sta in un solo insieme), ciascuna con tutte le zone e
uno schedule disabilitato con il suo `schedule_id`. `iu_config.sync_calls` la
trasforma in ciò che descrive `build_controller`, con le azioni di IU:
`load_schedule` (orario, evento solare, giorni, mesi, enabled),
`enable`/`disable` delle zone di sequenza e `adjust_time actual` sulle zone di
sequenza per le durate. `tests/test_iu_config_parity.py` verifica che struttura
più chiamate dia la configurazione effettiva, e le chiamate sono state provate
su un IU reale.

IU dimentica `load_schedule` a ogni riavvio e reload, quindi il runtime invia
di nuovo tutto quando compare l'entità del controller e dopo
`irrigation_unlimited.reload`. Negli altri casi invia solo le chiamate
cambiate. Ogni controller della struttura ha un digest sotto `user:`, che IU
espone come `user_hydroflow_structure` sull'entità del controller. Un digest
diverso vuol dire che il file incollato è vecchio: quel controller non riceve
chiamate e un avviso di riparazione mostra il nuovo testo. Il digest cambia
solo con la topologia e con eco (`repeat`, `delay`).

Le durate stanno sulle zone di sequenza. IU ignora un aggiustamento di zona
dentro una sequenza che ne ha uno suo, quindi anche Smart Irrigation scrive lì
il suo valore, per programma (`rt.si_override`), e gli aggiustamenti di zona
vengono azzerati a ogni invio completo.

## Una sequenza per ogni insieme di zone

Ogni zona di un programma può avere giorni della settimana diversi. Per ogni
giorno il builder calcola l'insieme delle zone che irrigano, poi raggruppa in
un'unica sequenza i giorni con lo stesso insieme. Ogni giorno appartiene a
esattamente una sequenza. Tutte le sequenze di un programma condividono il suo
orario di partenza, quindi se due avessero lo stesso giorno IU le avvierebbe in
parallelo. Gli slot di `sequence_id` sono fissi: il programma N possiede
`(N-1)*zone+1 .. N*zone`.

## Le azioni temporizzate si ancorano alla prossima partenza di IU

Riempimento, preflight e aggiornamento di Smart Irrigation scattano a
`start − anticipo`. `start` è il `sequence_status[].start` più vicino tra le
sequenze del programma sull'entità del controller. Quel valore viene da IU, che
tiene già conto di giorni, mesi, alba e tramonto, offset e sospensioni. Nulla
reimplementa la programmazione. I timer vengono ripianificati a ogni modifica
dell'entità del controller, a ogni cambio di anticipo e ogni 15 minuti. Ogni
occorrenza scatta al massimo una volta.

La versione YAML confrontava `sensor.time` con `HH:MM` e prendeva il giorno
della settimana dall'ora di scatto. Quando un anticipo attraversava la
mezzanotte, controllava il giorno sbagliato.

## Preflight

Il problema: con il device delle valvole offline, IU conta comunque la corsa e
riporta `actual == planned`. La soglia del 90% sull'azzeramento del bucket non
può accorgersene, quindi i bucket venivano azzerati senza che fosse uscita
acqua. Ci sono tre livelli di difesa:

1. Timer di preflight a `start − timeout`. Attende il device per al massimo
   `timeout − 1` minuti (almeno 1), così la sospensione arriva prima che IU
   parta. Se il device non torna, sospende per la durata prevista della corsa
   più 600 s e registra il motivo `device_offline`. Non fa nulla se il
   controller è già sospeso.
2. A `irrigation_unlimited_start` con il device offline, la corsa viene
   annullata. Vale anche per le corse manuali.
3. L'azzeramento del bucket richiede che il device sia online alla fine.

Le notifiche di preflight e di salto per pioggia ignorano l'interruttore
`notifications` del controller. Quell'interruttore silenzia i messaggi
ordinari di inizio e fine, non i guasti.

## Gli eventi di IU sono a livello di sequenza

Gli eventi di inizio e fine portano `data.zones` (una lista) e
`data.entity_id` (l'entità della sequenza). `data.zone` esiste solo su
`valve_on` e `valve_off`. L'azzeramento del bucket salva le zone previste
all'inizio e le confronta, zona per zona, con l'evento di fine della stessa
entità di sequenza.

## La pausa eco è in secondi

Il vecchio helper era etichettato "min", ma il suo valore arrivava sempre al
`delay` di IU come secondi. L'entità ora è in secondi. Può essere negativa: in
quel caso IU sovrappone i cicli.

## L'interruttore del motore

Quando `engine_enabled` è spento, l'integrazione espone solo le entità. Non
invia niente a IU e non avvia timer né gestori di eventi. Così si può
installare accanto ai pacchetti YAML che sostituisce senza che agiscano
entrambi insieme.

## Dashboard

La dashboard viene generata da `dashboard_templates/*.j2` e salvata come
dashboard storage. La collection delle dashboard di Lovelace è privata, quindi
l'integrazione registra la dashboard da sola: un `LovelaceStorage` più un
pannello. Per questo non compare in Impostazioni → Plance. Scrive solo quella
dashboard: se l'URL appartiene a un'altra, non salva niente e un avviso di
riparazione chiede un altro URL. Una nuova
generazione viene salvata solo quando cambia il suo digest, oppure su
richiesta.
Il grafico storico della vista Zone richiede apexcharts-card: viene generato
solo quando quella risorsa è registrata (o quando le risorse non si possono
leggere), quindi installa la card e premi *Rigenera dashboard* per ottenerlo.
Le modifiche manuali durano fino al successivo cambio di configurazione.

Tutte le card sono button-card; le card native compaiono solo annidate dentro
una di esse (il grafico apexcharts). Anche stepper, interruttori e selettori
segmentati sono button-card, quindi numberbox-card e auto-entities non servono
più. Ogni impianto ha quattro viste: la prima mantiene il vecchio percorso
`irrigazione-<id>`, le altre aggiungono `-programmi`, `-zone`, `-impostazioni`.
Le altre tre sono subview, raggiunte dall'intestazione nella pagina: una vista
nascosta mostra comunque la sua scheda mentre è aperta, una subview mai, e al
suo posto ha una freccia per tornare al controller.

### Temi

I colori stanno in `palettes.py`: gli stessi nomi di token per ogni tema e
modalità. `hf_base` legge dal vivo `select.iu_dashboard_theme` e
`select.iu_dashboard_mode` e pubblica la palette come proprietà CSS `--hf-*`
sulla card; le card annidate le ereditano dal DOM. `system` collega i token
alle variabili del tema di Home Assistant, quindi con questo tema la modalità
non ha effetto. Lo sfondo della pagina non si può colorare da una card: le
viste ricevono un `background` statico solo con un tema HydroFlow e una
modalità fissa, e un cambio di uno dei due select rigenera la dashboard.

I template scritti direttamente nella configurazione di una card annidata
vengono valutati dalla card che la contiene (button-card fa così salvo
`do_not_eval`): le loro entità devono stare nel `triggers_update` della card
esterna, altrimenti non si aggiornano.
