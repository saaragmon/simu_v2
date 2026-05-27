# Event Handling Diagrams

This document presents the handling flowcharts for **three representative events**
from the Queuechella simulation, as required by the project brief.

Each diagram shows:
- **Inputs** — what the event carries when popped from the heap
- **State changes** — which simulation variables are mutated
- **Conditions** — branches taken based on system state
- **Scheduled events** — what new Event objects are pushed to the heap
- **Termination** — when the handler returns

The three events were chosen to illustrate three different patterns:

| # | Event | Pattern illustrated |
|---|---|---|
| 1 | `EntityArriveEvent` | Simple entry + a single decision point (server free vs queue) |
| 2 | `StageBreakEndEvent` | One event creates **multiple downstream events** at once |
| 3 | `StationServiceEndEvent` | Complex post-service flow with abandonment cancellation and conditional routing |

For the overall system flow, see the system / event diagram in the report
(separate file). All handlers live in `events.py`; the engine simply calls
`event.handle(sim)` after popping it.

---

## Event 1 — `EntityArriveEvent`

> **When fired:** A new entity arrives at the festival entry gate. Scheduled at
> simulation start by `_schedule_arrivals` for every FriendsGroup, Couple, and
> Single arrival time generated from the configured inter-arrival distribution.

**Inputs:**
- `time` — arrival clock value
- `entity_type` — one of `'FriendsGroup'`, `'Couple'`, `'Single'`
- `day` — 1 or 2

**Diagram:**

```
                    ┌──────────────────────────────────┐
                    │   EntityArriveEvent.handle(sim)  │
                    │   inputs: time, entity_type, day │
                    └──────────────────┬───────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────┐
                    │  entity = create_entity(...)      │
                    │  sim._active_entities.add(entity) │
                    │  gate.enqueue(entity)             │
                    └──────────────────┬───────────────┘
                                       │
                                       ▼
                              ╱──────────────────╲
                             ╱  is a server free  ╲
                            ╱   at EntryGate?      ╲
                            ╲                      ╱
                             ╲──────┬────────┬───╱
                                    │        │
                                  YES        NO
                                    │        │
                                    ▼        ▼
                  ┌──────────────────────┐  ┌─────────────────────────┐
                  │ gate.acquire_server()│  │ entity stays in queue.  │
                  │ service_time =       │  │ Nothing new scheduled.  │
                  │   gate.sample_       │  │                         │
                  │   service_time()     │  │ Will be served by a     │
                  │                      │  │ future                  │
                  │ schedule:            │  │ EntryServiceEndEvent    │
                  │   EntryServiceEnd-   │  │ that pops the queue.    │
                  │   Event(             │  └──────────┬──────────────┘
                  │     time =           │             │
                  │     clock+service,   │             │
                  │     entity = entity) │             │
                  └──────────┬───────────┘             │
                             │                         │
                             └───────────┬─────────────┘
                                         │
                                         ▼
                                     ( return )
```

**Why this matters in the model:** the gate is the only mandatory queue —
every visitor goes through it. The early branching here decides whether the
visitor experiences an entry wait or gets served immediately.

---

## Event 2 — `StageBreakEndEvent`

> **When fired:** A stage's inter-show break has ended; the next performance
> can begin. Scheduled at simulation start (the first show of the day) and by
> `StageShowEndEvent` (the next break-end after each show).

**Inputs:**
- `time` — clock value at which the break finishes
- `stage_name` — `'MainStage'` or `'SideStage'` (DJ stage runs continuously)
- `day` — 1 or 2

**Diagram:**

```
              ┌────────────────────────────────────────┐
              │  StageBreakEndEvent.handle(sim)        │
              │  inputs: time, stage_name, day         │
              └─────────────────────┬──────────────────┘
                                    │
                                    ▼
                          ╱───────────────────────╲
                         ╱  clock >= day_end?      ╲
                         ╲    (festival day over)   ╱
                          ╲──────┬───────────┬───╱
                                 │           │
                                YES          NO
                                 │           │
                                 ▼           ▼
                            (return)   ┌──────────────────────────┐
                                       │ duration =                │
                                       │   stage.sample_show_      │
                                       │   duration()              │
                                       │ show_end = clock+duration │
                                       │ if show_end > day_end:    │
                                       │   show_end = day_end      │
                                       └────────────┬──────────────┘
                                                    │
                                                    ▼
                                       ┌──────────────────────────┐
                                       │ admitted =                │
                                       │   stage.start_show(       │
                                       │     show_end)             │
                                       │  (MaxFill from queue)     │
                                       └────────────┬──────────────┘
                                                    │
                                                    ▼
                                       ╱───────────────────────────╲
                                      ╱  for each entity in         ╲
                                     ╱   admitted:                   ╲
                                     ╲     schedule                  ╱
                                      ╲    StageEnterEvent(         ╱
                                       ╲     clock, entity,        ╱
                                        ╲    stage_name)          ╱
                                         ╲─────────┬────────────╱
                                                   │
                                                   ▼
                                       ┌──────────────────────────┐
                                       │ schedule                  │
                                       │   StageShowEndEvent(      │
                                       │     show_end,             │
                                       │     stage_name,           │
                                       │     day=day,              │
                                       │     entity=None)          │
                                       └────────────┬──────────────┘
                                                    │
                                                    ▼
                                                ( return )
```

**Why this matters in the model:** this single handler spawns **N + 1 new
events** — one `StageEnterEvent` for every entity that the MaxFill policy
admits, plus one `StageShowEndEvent` for the performance's end. This is a
classic DES pattern of "one event = many follow-ups."

---

## Event 3 — `StationServiceEndEvent`

> **When fired:** Service at a station (Photo, Charging, Merch, BodyArt)
> completes for the served entity. Also fires as a special variant for
> BodyArt artist break-end (`station_name == 'BodyArt_break_end'`).

**Inputs:**
- `time` — clock at which service ends
- `entity` — the entity who just finished service (or `None` for break-end)
- `station_name` — e.g. `'PhotoStation'`, `'MerchTent'`, `'BodyArt'`, or
  `'BodyArt_break_end'`
- `all_stations_mode` — True if this visit was part of a FriendsGroup
  "AllStations" tour
- `artist_idx` — only set for break-end events

**Diagram:**

```
       ┌──────────────────────────────────────────────────────────┐
       │  StationServiceEndEvent.handle(sim)                       │
       │  inputs: time, entity, station_name, mode, artist_idx     │
       └──────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
                              ╱──────────────────────╲
                             ╱  station_name ==        ╲
                            ╱  'BodyArt_break_end' ?    ╲
                            ╲                           ╱
                             ╲──────┬──────────────┬──╱
                                    │              │
                                   YES             NO  (regular service-end)
                                    │              │
                                    ▼              ▼
                ┌─────────────────────┐    ┌──────────────────────────────┐
                │ ba.artist_break_done│    │ station.release_server()      │
                │   (artist_idx)      │    │ sim._apply_station_outcome(   │
                │ try serve next      │    │   station_name, entity)       │
                │ if queue non-empty  │    │   → updates satisfaction,     │
                │ and server free     │    │     spending, BodyArt drawing │
                └──────────┬──────────┘    │     counter, etc.             │
                           │               └─────────────┬────────────────┘
                           ▼                             │
                       (return)                          ▼
                                                ╱──────────────────╲
                                               ╱  entity is Couple? ╲
                                               ╲                    ╱
                                                ╲──┬────────────┬─╱
                                                   │            │
                                                  YES           NO
                                                   │            │
                                                   ▼            │
                                       ┌──────────────────────┐ │
                                       │ entity.on_station_   │ │
                                       │  completed()         │ │
                                       │  (re-plans next show)│ │
                                       └──────────┬───────────┘ │
                                                  │             │
                                                  └──────┬──────┘
                                                         │
                                                         ▼
                                       ┌─────────────────────────────────┐
                                       │ sim._try_serve_next(station,    │
                                       │                    station_name)│
                                       │   - pop next live entity        │
                                       │   - cancel its abandon event    │
                                       │   - record queue wait time      │
                                       │   - schedule a new              │
                                       │     StationServiceEndEvent      │
                                       │     for that entity             │
                                       └────────────────┬────────────────┘
                                                        │
                                                        ▼
                                                ╱──────────────────╲
                                               ╱  entity.departed?  ╲
                                               ╲   (already left)   ╱
                                                ╲──┬────────────┬─╱
                                                   │            │
                                                  YES           NO
                                                   │            │
                                                   ▼            ▼
                                                (return)   ┌───────────────────────┐
                                                           │ sim._after_station(    │
                                                           │   entity,              │
                                                           │   all_stations_mode)   │
                                                           │                        │
                                                           │  Schedules ONE of:     │
                                                           │  - AllStationsNext     │
                                                           │      (more stations    │
                                                           │       pending in tour) │
                                                           │  - AllStationsDone     │
                                                           │      (tour completed)  │
                                                           │  - EntityNextActivity  │
                                                           │      (regular case)    │
                                                           └───────────┬───────────┘
                                                                       │
                                                                       ▼
                                                                  ( return )
```

**Why this matters in the model:** this is the **most branching-heavy** event
in the whole simulation. It has:
- a separate sub-path for the BodyArt break-end variant
- a side-effect on satisfaction / spending / counters
- queue progression with abandon cancellation
- conditional next-activity routing depending on whether the entity is part
  of an AllStations tour, has departed mid-service, etc.

Studying this one handler gives a good feel for how a single event can
encode a lot of business logic while still staying within the DES paradigm.

---

## Summary

Across the three diagrams the recurring DES building blocks are visible:

1. **State update** — the handler mutates the simulation's mutable state
   (queues, server counters, satisfaction, etc.).
2. **Conditional logic** — `if/else` branches determine which path is taken.
3. **Event scheduling** — the handler may push 0, 1, or many new events onto
   the heap, each with its own future timestamp.
4. **Termination** — once the handler returns, the engine loops back to pop
   the next earliest event from the heap.

This is exactly the polymorphic DES pattern from Tutorial 6 and the
HotelSimulation example project: **engine = pop + dispatch; events = logic.**
