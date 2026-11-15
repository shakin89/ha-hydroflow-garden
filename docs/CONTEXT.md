# Design notes

Decisions that the code alone does not explain. This integration replaces a
Python script that generated YAML packages. Its behaviour is pinned by
`tests/test_iu_config_parity.py`, which runs against a verbatim copy of that
script's builder.

## Value keys are the entity object_ids

`model.eid()` builds keys as `iu_<controller>_<parts>`. A key is the object_id
and the unique_id of the value's entity. It is also how the value is seeded from
the YAML helper with the same object_id. Changing the format breaks all three.
A zone or program id is part of its keys, so changing an id creates a new zone.

The per-zone sensors (`..._programmato`, `..._oggi`) take their object_id from
the zone **name**, as the YAML sensors did. Renaming a zone therefore makes new
sensors.

## IU indices are positional

IU names its entities `c<N>_m`, `c<N>_z<M>` and `c<N>_s<M>` by **position** in
its YAML. For sequences, the position is not the `sequence_id`. Controllers are
ordered by the `order` field, which is assigned once when the controller is
created. IU entities are looked up in the entity registry by unique_id. Never
hardcode `_s<M>`. A program has several sequences, and their positions change
whenever the days change.

## One sequence per set of zones

A program's zones can each have different weekdays. For every weekday the
builder computes the set of zones that run, then groups days with the same set
into one sequence. Each weekday belongs to exactly one sequence. All sequences
of a program share its start time, so if two of them had the same weekday, IU
would start them in parallel. `sequence_id` slots are fixed: program N owns
`(N-1)*zones+1 .. N*zones`.

## Timed actions are anchored on IU's own next start

Fill, preflight and the Smart Irrigation adjust fire at
`start − lead`. `start` is the earliest `sequence_status[].start` of the
program's sequences on the controller entity. That value comes from IU, which
already accounts for weekdays, months, sunrise and sunset, offsets and
suspensions. Nothing re-implements the schedule. The timers are re-planned on
every change of the controller entity, on lead changes, and every 15 minutes.
Each occurrence fires at most once.

The YAML version compared `sensor.time` with `HH:MM` and took the weekday from
the fire time. When a lead crossed midnight, it checked the wrong day.

## Preflight

The problem: with the valve device offline, IU still counts the run and reports
`actual == planned`. The 90% guard on the bucket reset cannot see this, so
buckets were zeroed without any water. There are three layers of defence:

1. Preflight timer at `start − timeout`. It waits for the device for at most
   `timeout − 1` minutes (at least 1), so the suspend lands before IU starts.
   If the device does not come back, it suspends for the planned run length
   plus 600 s and records the reason *Device offline*. It does nothing when the
   controller is already suspended.
2. At `irrigation_unlimited_start` with the device offline, the run is
   cancelled. This includes manual runs.
3. The bucket reset requires the device to be online at finish.

Preflight and rain-skip notifications ignore the per-controller
`notifications` switch. That switch silences routine start and finish
messages, not faults.

## IU events are sequence-level

Start and finish events carry `data.zones` (a list) and `data.entity_id`
(the sequence entity). `data.zone` only exists on `valve_on` and `valve_off`.
The bucket reset stores the planned zones at start and compares them, per
zone, with the finish event for the same sequence entity.

## Eco soak is in seconds

The old helper was labelled "min", but its value always reached IU's `delay`
as seconds. The entity is now in seconds. It can be negative, in which case IU
overlaps the cycles.

## The engine switch

When `engine_enabled` is off, the integration only exposes entities. It writes
no IU file and runs no timers or event handlers. This allows installing it next
to the YAML packages it replaces without both acting at once.

## Dashboard

The dashboard is rendered from `dashboard_templates/*.j2` and saved as a
storage dashboard. Lovelace's dashboards collection is private, so the
integration registers the dashboard itself: a `LovelaceStorage` plus a panel.
It is therefore not listed under Settings → Dashboards. When a storage
dashboard with the same URL already exists, it is written in place. A new
render is saved only when its digest changes, or on demand.
The Timeline tab needs apexcharts-card: it is rendered only when that resource
is registered (or when the resources cannot be read), so install the card and
press *Rigenera dashboard* to get it. Manual edits last
until the next configuration change.
