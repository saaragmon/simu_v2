# Queuechella Festival Simulation — Project Notes

This file briefs Claude Code on the project. Read it before answering questions.

## What this is

A discrete-event simulation (DES) of a 2-day music festival, written for the
Simulation course (Semester B 2026, BGU). The festival has visitors (entities),
queues at stations and stages, and the model evaluates alternative scenarios
against a baseline.

Entry point: `main.py`. Run with `python3 main.py`.

## Architecture in one breath

`engine.py` is the entire simulation. Everything else is content.

The core loop (engine.py lines ~139-144):

```python
while self.heap:
    event = heapq.heappop(self.heap)
    self.clock = event.time
    self._dispatch(event)
```

That is the whole DES. The 18 event types in `events.py` get routed by
`_dispatch()` to 18 `_handle_*` methods.

## Module map

| File                    | Role                                                     |
| ----------------------- | -------------------------------------------------------- |
| `engine.py`             | The DES engine: clock, heap, dispatcher, all handlers    |
| `events.py`             | `Event` dataclass + `EventType` enum (18 types)          |
| `entities.py`           | `FriendsGroup`, `Couple`, `Single` — visitor classes     |
| `stations.py`           | All physical locations: stations, stages, Festival       |
| `distributions.py`      | Box-Muller, Inverse Transform, Composition, Accept-Reject|
| `distribution_fitting.py` | Load Excel + fit Exp/Normal/Uniform + KS test           |
| `sim_stats.py`          | `RunStatistics` + `MultiRunStatistics` (CIs, t-tests)    |
| `alternatives.py`       | Scenario combos (Baseline, Combo_A, Combo_B)             |
| `config.py`             | `SimConfig` dataclass with all tunable parameters        |
| `main.py`               | CLI entry: pilot study, full runs, compare, recommend    |
| `samples_for_simulation.xlsx` | Real data: friends inter-arrival + main-stage durations |

## DES vocabulary mapping

| Concept              | In the code                              |
| -------------------- | ---------------------------------------- |
| Clock                | `self.clock: float` in Simulation        |
| Event list           | `self.heap: List[Event]` (a heapq min-heap) |
| Event                | `@dataclass(order=True) Event` in events.py |
| Tie-break ordering   | `tie_break` field auto-incremented in `make_event()` |
| Schedule new event   | `self._schedule_event(dt, type, entity)` |
| Dispatch             | `_dispatch(event)` — 18 elif branches    |
| State variables      | `self.festival` (queues, server counts), per-entity state |
| Statistics           | `self.stats = RunStatistics()`           |

## Entity types

- **FriendsGroup** (size 3-6, day 1 only, 09:00-13:00 arrivals): does 3 shows
  in random order, after each show visits ALL stations in shortest-queue order.
  Overnight stay with p=0.7 (decided at creation).
- **Couple** (size 2, day 1 or 2, 10:00-16:00 arrivals): alternates show <->
  station randomly. Avoids DJStage. Stays overnight only if satisfaction > 7.0.
- **Single** (size 1, day 1 or 2, 09:00-16:00 arrivals): fixed plan:
  MerchTent -> 2 MainStage -> 2 SideStage -> DJStage. One day only.

## Stations & stages

Service stations (FIFO queues with N servers):
- EntryGate (5), PhotoStation (3), ChargingStation (150), MerchTent (7),
  BodyArt (2 artists, mandatory break every 10), FoodStall x3 (1 each).

Concert stages (capacity-limited arena + queue):
- MainStage (200), SideStage (100), DJStage (70 concurrent).
- MainStage: back-row entities may leave 15 min after entry with p=0.5.

## KPIs

- `avg_satisfaction` — mean satisfaction score [0-10]. Higher is better.
- `total_revenue` — total NIS collected. Higher is better.
- `avg_queue_length` — time-weighted mean queue length across stations. Lower is better.

Multi-run analysis uses Student-t confidence intervals (CL=90%, relative
precision 10%) and paired t-tests. See `sim_stats.MultiRunStatistics`.

## Alternatives currently configured

Budget cap: 1,000,000 NIS per combo.

- **Combo_A** (650k): Extra photo+art (150k) + Popular bands (300k) + Gift bag (200k).
  Targets satisfaction.
- **Combo_B** (700k): Better kitchen (500k) + Marketing (200k). Targets revenue
  and throughput.

Seven building blocks total — see `alternatives.py` and `config.py` for the
full list including ones not currently combined.

## History (May 2026)

A code review found and fixed these bugs:

1. **EntryGate timing bug** (engine.py `_handle_entry_end`): the next entity's
   service was scheduled at `self.clock` instead of `self.clock + service_time`,
   so the gate processed entities instantly. Fixed.
2. **Food queue logic** (engine.py `_handle_food_queue_join`): entities were
   enqueued even when a server was free, then `dequeue()` in service-end pulled
   the same entity again. Wait stats were also wrong. Refactored to mirror the
   regular station pattern.
3. **Overnight logic** (engine.py `_handle_day_end`): was a no-op `pass`. Now
   actually decides per entity:
   - Couple: stays if `satisfaction > 7.0`, charged overnight fee, day=2.
   - FriendsGroup: stays if its `stays_overnight` flag (set at creation, p=0.7).
   - Single: always departs.
   Day-2 day_end force-departs anyone still in the system so every entity is
   recorded in stats. Added `self._active_entities: Set[Entity]` to track them.
4. **Recommendation direction** (main.py FINAL RECOMMENDATIONS): used `max()`
   for all KPIs, which is wrong for `avg_visit_duration` (lower is better). Now
   uses a `KPI_HIGHER_IS_BETTER` dict to pick the right selector.
5. **Comparison arrows** (main.py `print_comparison`): showed up/down without
   knowing the KPI's direction. Now shows "better"/"worse".
6. **STATION_SERVICE_START** event type was unused; removed it from
   `EventType` and the dispatcher.
7. **Dispatcher hardening**: unhandled event types now raise instead of
   silently being skipped.
8. **MerchTent**: removed a dead `u = dist.sample_uniform_01` reference.
9. **pizza_family_serves** is now a proper field on `SimConfig` instead of
   being looked up via `cfg.__class__.__dict__.get(...)`.
10. **.gitignore** added; stopped tracking `__pycache__/*.pyc`.

Renames (no behavior change):
- `avg_sojourn_min` / `avg_sojourn_time` -> `avg_visit_duration` everywhere
  ("sojourn" was opaque jargon)
- `_sched()` -> `_schedule_event()`
- `_values()` -> `_kpi_values()` in MultiRunStatistics

## How to run

```bash
python3 main.py                 # default: pilot + full + alternatives
python3 main.py --runs 30       # override replication count
python3 main.py --verbose       # print event log for first run of each scenario
python3 main.py --no-fit        # skip Excel fitting, use built-in defaults
```

Excel reading requires `openpyxl`: `pip install openpyxl`.

## Where to look first when answering questions

- "How does X event work?" -> `engine.py` `_handle_X` method.
- "Why does entity behavior Y happen?" -> `entities.py` then trace through
  `_handle_next_activity` and the routing methods (`_route_friends_group`, etc).
- "How is duration Z sampled?" -> `distributions.py` then the station class in
  `stations.py`.
- "What does KPI W mean?" -> `sim_stats.py` properties on `RunStatistics`.
- "Why did the simulation pick this distribution?" ->
  `distribution_fitting.best_fit()` — selects by smallest KS statistic.

## Conventions

- All times are in **minutes from midnight of day 1**. `FESTIVAL_START = 540`
  (09:00), `DAY_DURATION = 660`. Day 2 starts immediately at t=1200 in the
  model — there is no real overnight gap in simulated time.
- Entities move as a unit; `size` determines how many real people they occupy.
- "Departed" entities are kept out of future processing but stay in
  `stats.entity_records` for analysis.

## Repo

https://github.com/saaragmon/simu_v2
