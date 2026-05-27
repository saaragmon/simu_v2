# Event-Handling Diagrams (Mermaid format)

These are the same three flowcharts as `event_handling_diagrams.md`, but
written in **Mermaid** syntax so they can be imported into draw.io
(or rendered automatically by GitHub / VS Code / Colab Markdown).

## How to import into draw.io

1. Open [app.diagrams.net](https://app.diagrams.net)
2. `Arrange` (top toolbar) → `Insert` → `Advanced` → `Mermaid...`
3. Paste the Mermaid block (everything between the ` ```mermaid ` fences)
4. Click `Insert` — the diagram appears on the canvas, fully editable

Once inserted you can:
- Drag/resize boxes
- Change colors and fonts
- Export as PNG / SVG / PDF
- Save as `.drawio` for later editing

---

## 1. `EntityArriveEvent`

A new entity arrives at the festival entry gate.

```mermaid
flowchart TD
    Start([EntityArriveEvent.handle<br/>inputs: time, entity_type, day])
    Create[Create entity<br/>add to active_entities<br/>enqueue at EntryGate]
    Decision{Server free<br/>at EntryGate?}
    Acquire[gate.acquire_server<br/>service_time = gate.sample_service_time]
    Schedule[/Schedule EntryServiceEndEvent<br/>at clock + service_time/]
    Wait[Stay in queue<br/>no new event scheduled]
    Done([Return])

    Start --> Create
    Create --> Decision
    Decision -->|YES| Acquire
    Acquire --> Schedule
    Schedule --> Done
    Decision -->|NO| Wait
    Wait --> Done

    classDef event fill:#fef3c7,stroke:#92400e
    classDef decision fill:#fee2e2,stroke:#991b1b
    classDef action fill:#dbeafe,stroke:#1e40af
    classDef terminal fill:#d1fae5,stroke:#065f46
    class Start,Done terminal
    class Create,Acquire,Wait action
    class Schedule event
    class Decision decision
```

---

## 2. `StageBreakEndEvent`

A stage's inter-show break has ended; the next performance can begin.
**Key pattern:** one event spawns N+1 follow-up events.

```mermaid
flowchart TD
    Start([StageBreakEndEvent.handle<br/>inputs: time, stage_name, day])
    DayCheck{clock >= day_end?<br/>festival day over}
    Duration[duration = stage.sample_show_duration<br/>show_end = clock + duration<br/>truncate at day_end if needed]
    Admit[admitted = stage.start_show show_end<br/>MaxFill from queue]
    EachEnter[/For each admitted entity:<br/>schedule StageEnterEvent/]
    SchedShowEnd[/Schedule StageShowEndEvent<br/>at show_end/]
    Done([Return])

    Start --> DayCheck
    DayCheck -->|YES| Done
    DayCheck -->|NO| Duration
    Duration --> Admit
    Admit --> EachEnter
    EachEnter --> SchedShowEnd
    SchedShowEnd --> Done

    classDef decision fill:#fee2e2,stroke:#991b1b
    classDef action fill:#dbeafe,stroke:#1e40af
    classDef event fill:#fef3c7,stroke:#92400e
    classDef terminal fill:#d1fae5,stroke:#065f46
    class Start,Done terminal
    class Duration,Admit action
    class EachEnter,SchedShowEnd event
    class DayCheck decision
```

---

## 3. `StationServiceEndEvent`

Service at a station completes for the served entity.
**Key pattern:** most-branching handler in the model.

```mermaid
flowchart TD
    Start([StationServiceEndEvent.handle<br/>inputs: time, entity, station_name, mode, artist_idx])
    BreakCheck{station_name ==<br/>BodyArt_break_end?}
    BreakDone[ba.artist_break_done<br/>try_serve_next on BodyArt queue]
    Release[station.release_server<br/>apply_station_outcome:<br/>satisfaction, spending, counters]
    CoupleCheck{entity is Couple?}
    OnComplete[entity.on_station_completed<br/>re-plans next show]
    TryServe[try_serve_next station, station_name:<br/>pop next live entity, cancel abandon,<br/>record wait, schedule new ServiceEnd]
    DepartCheck{entity.departed?<br/>already left}
    After[/after_station entity, mode<br/>schedules ONE of:<br/>- AllStationsNext<br/>- AllStationsDone<br/>- EntityNextActivity/]
    Done([Return])

    Start --> BreakCheck
    BreakCheck -->|YES| BreakDone
    BreakDone --> Done
    BreakCheck -->|NO| Release
    Release --> CoupleCheck
    CoupleCheck -->|YES| OnComplete
    OnComplete --> TryServe
    CoupleCheck -->|NO| TryServe
    TryServe --> DepartCheck
    DepartCheck -->|YES| Done
    DepartCheck -->|NO| After
    After --> Done

    classDef decision fill:#fee2e2,stroke:#991b1b
    classDef action fill:#dbeafe,stroke:#1e40af
    classDef event fill:#fef3c7,stroke:#92400e
    classDef terminal fill:#d1fae5,stroke:#065f46
    class Start,Done terminal
    class BreakDone,Release,OnComplete,TryServe action
    class After event
    class BreakCheck,CoupleCheck,DepartCheck decision
```

---

## Colour legend

The `classDef` styles produce a colour-coded diagram in draw.io:

| Colour | Meaning |
|---|---|
| 🟢 Green | Start / End (entry & exit of the handler) |
| 🔵 Blue | State change / function call |
| 🟡 Yellow | Event scheduled onto the heap |
| 🔴 Red | Decision (if/else) |

After import you can tweak the colours via the Format panel on the right.

---

## Tip for the Colab report

If you want the diagrams to render automatically in the Colab notebook,
just paste the ```` ```mermaid ```` block into a Markdown cell.
Modern Colab supports Mermaid in Markdown cells natively, so they will
render as proper flowcharts without needing image files at all.
