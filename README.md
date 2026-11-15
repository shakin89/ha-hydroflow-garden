# Irrigation Manager

Home Assistant integration that plans [Irrigation Unlimited](https://github.com/rgc99/irrigation_unlimited)
(IU) from the UI. You describe controllers, zones and programs once; you then
set days, durations, months, eco cycles and start times from entities on a
generated dashboard. The integration writes IU's YAML configuration and
reloads IU whenever a value changes. IU stays the one that opens the valves.

On top of the schedule it runs what is usually a pile of automations:

| Feature | What it does |
|---|---|
| Per-zone weekdays | Each zone of a program has its own weekdays. Every weekday lands in one IU sequence, so zones never open together. |
| Eco | The zone duration is the total; IU repeats the program N cycles with a soak between them. |
| Cistern fill | Turns fill switches on N minutes before a program, for M minutes. |
| Preflight | When the valve device (a connectivity `binary_sensor`) is offline before a run, waits for it and otherwise suspends the controller. A run starting with the device offline is cancelled. |
| Smart Irrigation | Before each program, refreshes [Smart Irrigation](https://github.com/jeroenterheerdt/HAsmartirrigation) and sets each zone's duration from its sensor (`adjust_time`). After a run, resets the bucket of the zones that delivered at least 90% of the plan, and only if the device was online. |
| Rain | Every day at a set time, suspends the active controllers when the forecast probability and the forecast mm are both over thresholds. Cancels scheduled runs that start while it rains. |
| Notifications | Start, finish, cancel, rain, device offline. Sent to notify entities, legacy notify services and persistent notifications. |
| Event log | A plain text log with size rotation. |
| Dashboard | A storage dashboard generated from templates. It is rewritten whenever the configuration changes, or on demand. |

## Requirements

- Irrigation Unlimited, with its configuration included from a file:
  ```yaml
  # configuration.yaml
  irrigation_unlimited: !include irrigation_unlimited.yaml
  ```
  **That file is owned by this integration.** It is overwritten.
- For the dashboard: `button-card`, `auto-entities` and `apexcharts-card` (HACS frontend).
- Optional: Smart Irrigation and a `weather` entity with daily forecasts.

## Install

HACS → Integrations → ⋮ → Custom repositories → `https://github.com/shakin89/ha-irrigation-manager`
(category *Integration*). Install, restart, then Settings → Devices & services → Add integration → *Irrigation Manager*.

Add controllers with **Add controller**: pump entity, zones (id, name, valve switch, optional Smart
Irrigation sensor), programs (id, name, default time) and optional fill switches and connectivity sensor.

The **engine** switch in the options is off by default. Until you turn it on, entities exist but
nothing is written or triggered. This lets you migrate without two systems acting at once.

## Entities

Each value is an entity whose object_id is `iu_<controller>_...`. The entity_id does not change when
you edit a controller, as long as the zone and program ids stay the same.

- `switch.iu_<c>_system_enabled`, `_adjust_rain`, `_logging`, `_notifications`, `_preflight`
- `switch.iu_<c>_p<N>_enabled`, `_eco`, `_<month>`, `_z<Z>_enabled`, `_z<Z>_<weekday>`
- `number.iu_<c>_p<N>_z<Z>_duration` (min), `_offset` (min), `_eco_cycles`, `_eco_soak` (s), fill/preflight leads
- `time.iu_<c>_p<N>_time`, `select.iu_<c>_p<N>_time_type` (Fisso / Alba / Tramonto)
- `sensor.iu_<c>_suspend_reason`, per-zone *Programmato* and *Oggi / Ieri / 2gg fa* usage (hours)
- `button.iu_<c>_test`: runs every zone for the test duration

## Migrating from YAML helpers

At first start each value takes the state of the `input_boolean` / `input_number` / `input_datetime`
/ `input_select` with the **same object_id**, if one exists. To import a topology without
typing it, put it once in `configuration.yaml` and remove it after the first start:

```yaml
irrigation_manager:
  options:
    engine_enabled: false
  controllers:
    - id: garden
      name: Garden
      entity_id: switch.pump
      zones:
        - {id: 1, name: Lawn, entity_id: switch.valve_1, si_sensor: sensor.smart_irrigation_lawn}
        - {id: 2, name: Beds, entity_id: switch.valve_2}
      programs:
        - {id: 1, name: Morning, default_time: "06:00"}
      fill_switches: [switch.fill]
      availability_entity: binary_sensor.valves_status
```

## Actions

- `irrigation_manager.regenerate_dashboard`
- `irrigation_manager.write_iu_config`: rewrites the IU file and reloads IU
- `irrigation_manager.rain_skip` (`force: true` to test the suspension)

Design notes: [docs/CONTEXT.md](docs/CONTEXT.md).
