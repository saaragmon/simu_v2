"""
engine.py
=========
Core discrete-event simulation (DES) engine for Queuechella.

Architecture
------------
The engine maintains a priority queue (min-heap) of Events ordered by
simulation time.  The main loop pops the earliest event and dispatches it
to the appropriate handler method.

Event flow overview:
    1. Arrival generators schedule ENTITY_ARRIVE events at simulation start.
    2. ENTITY_ARRIVE → joins EntryGate queue → ENTRY_SERVICE_END (when clerk free).
    3. ENTRY_SERVICE_END → ENTITY_NEXT_ACTIVITY (entity in festival).
    4. ENTITY_NEXT_ACTIVITY:
          FriendsGroup → STAGE_QUEUE_JOIN (next show) or ALL_STATIONS_NEXT
          Couple       → STAGE_QUEUE_JOIN or STATION_QUEUE_JOIN (alternating)
          Single       → STATION_QUEUE_JOIN (Merch) then STAGE_QUEUE_JOIN
    5. STAGE_QUEUE_JOIN → wait for show / enter immediately (DJStage).
    6. STAGE_ENTER → STAGE_EARLY_LEAVE (back rows, MainStage) + STAGE_SHOW_END.
    7. STAGE_SHOW_END → satisfaction update → ENTITY_NEXT_ACTIVITY for audience.
    8. STATION_QUEUE_JOIN → wait for server / STATION_SERVICE_START immediately.
    9. STATION_SERVICE_END → outcome → ENTITY_NEXT_ACTIVITY.
   10. STATION_ABANDON → satisfaction penalty → ENTITY_NEXT_ACTIVITY.
   11. FOOD_QUEUE_JOIN → FOOD_SERVICE_END → FOOD_EAT_END → ENTITY_NEXT_ACTIVITY.
   12. DAY_END → overnight decisions.  Day 2 proceeds.
   13. SIM_END → collect statistics.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import deque
from typing import Dict, List, Optional, Tuple

from config import SimConfig, FESTIVAL_START, FESTIVAL_END, DAY_DURATION
import distributions as dist
from entities import (
    Entity, FriendsGroup, Couple, Single,
    create_entity, reset_entity_counter
)
from events import (
    Event, EventType, make_event, reset_event_counter
)
from stations import Festival, DJStage
from sim_stats import RunStatistics, EntityRecord


class SimulationEngine:
    """
    Event-driven simulation engine.

    Usage:
        engine = SimulationEngine(cfg)
        stats  = engine.run()
    """

    def __init__(self, cfg: SimConfig,
                 friends_arrival_sampler=None,
                 main_stage_duration_sampler=None,
                 verbose: bool = False):
        """
        Args:
            cfg                         : Simulation configuration.
            friends_arrival_sampler     : Callable → float (inter-arrival minutes).
                                          If None, falls back to fitted placeholder.
            main_stage_duration_sampler : Callable → float (show duration minutes).
                                          If None, falls back to Exponential(60).
            verbose                     : Print event log if True.
        """
        self.cfg     = cfg
        self.verbose = verbose

        # Distribution samplers (injected after fitting)
        self._friends_arrival = friends_arrival_sampler or self._default_friends_arrival
        self._main_stage_dur  = main_stage_duration_sampler or (
            lambda: dist.sample_exponential(60.0))

        # Simulation state
        self.clock:   float          = 0.0
        self.heap:    List[Event]    = []
        self.festival: Festival      = Festival(cfg)
        self.stats:   RunStatistics  = RunStatistics()

        # Track entities currently waiting in queues (for abandonment)
        # entity_id → abandon_event
        self._abandon_events: Dict[int, Event] = {}

        # Pending "AllStations" station list per entity_id
        self._pending_stations: Dict[int, List[str]] = {}

        # Artist assignment for BodyArt
        self._body_art_artist_map: Dict[int, int] = {}  # entity_id → artist_idx

    # ─────────────────────────────────────────────────────────────────────────
    # Default samplers (placeholders until Excel data is fitted)
    # ─────────────────────────────────────────────────────────────────────────

    def _default_friends_arrival(self) -> float:
        """
        FriendsGroup inter-arrival time (minutes).
        Placeholder: Exponential mean=5 min (≈12 groups/hour).
        REPLACE after fitting distribution to sheet 1 of the Excel file.
        """
        return dist.sample_exponential(5.0)

    # ─────────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────────

    def run(self) -> RunStatistics:
        """Execute the full 2-day simulation and return collected statistics."""
        reset_entity_counter()
        reset_event_counter()
        self.clock   = FESTIVAL_START
        self.heap    = []
        self.stats   = RunStatistics()

        # Re-initialise festival stations
        self.festival = Festival(self.cfg)
        self.festival.set_main_stage_sampler(self._main_stage_dur)

        self._schedule_arrivals()
        self._schedule_show_starts()
        self._schedule_day_ends()
        self._push(make_event(FESTIVAL_START + 2 * DAY_DURATION, EventType.SIM_END))

        while self.heap:
            event = heapq.heappop(self.heap)
            self.clock = event.time
            if self.verbose:
                print(f"  t={self.clock:7.2f}  {event}")
            self._dispatch(event)

        return self.stats

    # ─────────────────────────────────────────────────────────────────────────
    # Priority queue helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _push(self, event: Event) -> None:
        heapq.heappush(self.heap, event)

    def _sched(self, dt: float, event_type: EventType,
               entity: Optional[Entity] = None,
               data: Optional[dict] = None) -> Event:
        """Schedule an event `dt` minutes from now."""
        ev = make_event(self.clock + dt, event_type, entity, data)
        self._push(ev)
        return ev

    # ─────────────────────────────────────────────────────────────────────────
    # Initialisation: schedule all arrivals and show starts
    # ─────────────────────────────────────────────────────────────────────────

    def _schedule_arrivals(self) -> None:
        """Generate all entity arrivals for both festival days."""
        mult = self.cfg.arrival_rate_multiplier

        # FriendsGroup: Day 1, 09:00-13:00 only
        t = FESTIVAL_START
        fg_end = FESTIVAL_START + (4 * 60)  # 13:00
        while t < fg_end:
            ia = self._friends_arrival() / mult
            t += ia
            if t >= fg_end:
                break
            self._push(make_event(t, EventType.ENTITY_ARRIVE,
                                  data={'entity_type': 'FriendsGroup',
                                        'day': 1}))

        # Couple arrivals: both days 10:00-16:00
        for day in (1, 2):
            day_start = FESTIVAL_START + (day - 1) * DAY_DURATION
            arr_start = day_start + 60   # +1 h → 10:00
            arr_end   = day_start + 7 * 60  # +7 h → 16:00
            t = arr_start
            while t < arr_end:
                ia = dist.sample_exponential(self.cfg.couple_arrival_rate_per_min) / mult
                t += ia
                if t >= arr_end:
                    break
                self._push(make_event(t, EventType.ENTITY_ARRIVE,
                                      data={'entity_type': 'Couple', 'day': day}))

        # Single arrivals: each day 09:00-16:00
        for day in (1, 2):
            day_start = FESTIVAL_START + (day - 1) * DAY_DURATION
            arr_end   = day_start + 7 * 60  # 16:00
            t = day_start
            while t < arr_end:
                ia = dist.sample_exponential(
                    self.cfg.single_arrival_rate_per_min) / mult
                t += ia
                if t >= arr_end:
                    break
                self._push(make_event(t, EventType.ENTITY_ARRIVE,
                                      data={'entity_type': 'Single', 'day': day}))

    def _schedule_show_starts(self) -> None:
        """Schedule the first MainStage and SideStage shows for each day."""
        for day in (1, 2):
            day_start = FESTIVAL_START + (day - 1) * DAY_DURATION
            # MainStage: first show at day start
            self._push(make_event(day_start, EventType.STAGE_BREAK_END,
                                  data={'stage': 'MainStage', 'day': day}))
            # SideStage: first show at day start
            self._push(make_event(day_start, EventType.STAGE_BREAK_END,
                                  data={'stage': 'SideStage', 'day': day}))
            # DJStage is always running; no separate show events needed.

    def _schedule_day_ends(self) -> None:
        for day in (1, 2):
            t = FESTIVAL_START + day * DAY_DURATION
            self._push(make_event(t, EventType.DAY_END, data={'day': day}))

    # ─────────────────────────────────────────────────────────────────────────
    # Event dispatcher
    # ─────────────────────────────────────────────────────────────────────────

    def _dispatch(self, event: Event) -> None:
        et = event.event_type
        if   et == EventType.ENTITY_ARRIVE:          self._handle_arrive(event)
        elif et == EventType.ENTRY_SERVICE_END:       self._handle_entry_end(event)
        elif et == EventType.ENTITY_NEXT_ACTIVITY:   self._handle_next_activity(event)
        elif et == EventType.STAGE_QUEUE_JOIN:        self._handle_stage_queue_join(event)
        elif et == EventType.STAGE_ENTER:             self._handle_stage_enter(event)
        elif et == EventType.STAGE_EARLY_LEAVE:       self._handle_stage_early_leave(event)
        elif et == EventType.STAGE_SHOW_END:          self._handle_stage_show_end(event)
        elif et == EventType.STAGE_BREAK_END:         self._handle_stage_break_end(event)
        elif et == EventType.STATION_QUEUE_JOIN:      self._handle_station_queue_join(event)
        elif et == EventType.STATION_ABANDON:         self._handle_station_abandon(event)
        elif et == EventType.STATION_SERVICE_START:   self._handle_station_service_start(event)
        elif et == EventType.STATION_SERVICE_END:     self._handle_station_service_end(event)
        elif et == EventType.FOOD_QUEUE_JOIN:         self._handle_food_queue_join(event)
        elif et == EventType.FOOD_SERVICE_END:        self._handle_food_service_end(event)
        elif et == EventType.FOOD_EAT_END:            self._handle_food_eat_end(event)
        elif et == EventType.ALL_STATIONS_NEXT:       self._handle_all_stations_next(event)
        elif et == EventType.ALL_STATIONS_DONE:       self._handle_all_stations_done(event)
        elif et == EventType.DAY_END:                 self._handle_day_end(event)
        elif et == EventType.SIM_END:                 self._handle_sim_end(event)

    # ─────────────────────────────────────────────────────────────────────────
    # Arrival handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_arrive(self, event: Event) -> None:
        """Entity arrives at the festival and joins the entry gate queue."""
        entity = create_entity(event.data['entity_type'],
                               event.time,
                               event.data['day'],
                               self.cfg)
        gate = self.festival.entry_gate
        gate.enqueue(entity)

        if gate.is_server_available():
            gate.acquire_server()
            service_time = gate.sample_service_time()
            self._sched(service_time, EventType.ENTRY_SERVICE_END, entity)

    def _handle_entry_end(self, event: Event) -> None:
        """Entry service done: entity enters festival, server may take next."""
        entity = event.entity
        gate   = self.festival.entry_gate

        # Pay entry ticket
        has_overnight = False
        if isinstance(entity, FriendsGroup) and entity.stays_overnight:
            has_overnight = True
        elif isinstance(entity, Couple):
            pass  # overnight decided at end of day
        entity.pay_entry(has_overnight)
        self.stats.total_revenue += entity.spending  # initial ticket revenue

        gate.release_server()

        # Check if next entity is waiting
        next_entity = gate.dequeue()
        if next_entity is not None:
            gate.acquire_server()
            service_time = gate.sample_service_time()
            self._push(make_event(self.clock, EventType.ENTRY_SERVICE_END,
                                  next_entity))

        # Send entity into the festival
        self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)

    # ─────────────────────────────────────────────────────────────────────────
    # Activity routing
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_next_activity(self, event: Event) -> None:
        """
        Entity selects its next activity.

        Lunch check: if current time is within lunch window (13:00-15:00)
        and entity hasn't eaten yet, with probability food_lunch_prob it
        goes to eat.
        """
        entity = event.entity
        if entity.departed:
            return

        # ── Lunch check ───────────────────────────────────────────────────────
        if not getattr(entity, '_had_lunch', False):
            lunch_start = FESTIVAL_START + 4 * 60   # 13:00
            lunch_end   = FESTIVAL_START + 6 * 60   # 15:00
            if lunch_start <= self.clock <= lunch_end:
                if dist.sample_uniform_01() < self.cfg.food_lunch_prob:
                    entity._had_lunch = True
                    self._send_to_food(entity)
                    return

        # ── Determine next activity ───────────────────────────────────────────
        if isinstance(entity, FriendsGroup):
            self._route_friends_group(entity)
        elif isinstance(entity, Couple):
            self._route_couple(entity)
        elif isinstance(entity, Single):
            self._route_single(entity)

    def _route_friends_group(self, entity: FriendsGroup) -> None:
        """
        FriendsGroup routing:
            Activity plan contains show names and 'AllStations' sentinel.
        """
        activity = entity.next_activity()
        if activity is None:
            self._depart(entity)
        elif activity == 'AllStations':
            # Build ordered station list by shortest queue now
            ordered = self.festival.ordered_stations_by_queue()
            self._pending_stations[entity.entity_id] = ordered
            self._push(make_event(self.clock, EventType.ALL_STATIONS_NEXT,
                                  entity))
        elif activity in ('MainStage', 'SideStage', 'DJStage'):
            self._push(make_event(self.clock, EventType.STAGE_QUEUE_JOIN,
                                  entity, {'stage': activity}))
        else:
            self._push(make_event(self.clock, EventType.STATION_QUEUE_JOIN,
                                  entity, {'station': activity}))

    def _route_couple(self, entity: Couple) -> None:
        """
        Couple routing: alternate show ↔ station dynamically.
        """
        activity = entity.next_activity()
        if activity is None:
            self._depart(entity)
        elif activity in ('MainStage', 'SideStage', 'DJStage'):
            # Couple dislikes DJStage; if somehow scheduled, skip
            if activity == 'DJStage':
                entity.on_show_completed()
                self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)
            else:
                self._push(make_event(self.clock, EventType.STAGE_QUEUE_JOIN,
                                      entity, {'stage': activity}))
        else:
            self._push(make_event(self.clock, EventType.STATION_QUEUE_JOIN,
                                  entity, {'station': activity}))

    def _route_single(self, entity: Single) -> None:
        """Single routing: follows fixed activity plan."""
        activity = entity.next_activity()
        if activity is None:
            self._depart(entity)
        elif activity in ('MainStage', 'SideStage', 'DJStage'):
            self._push(make_event(self.clock, EventType.STAGE_QUEUE_JOIN,
                                  entity, {'stage': activity}))
        else:
            self._push(make_event(self.clock, EventType.STATION_QUEUE_JOIN,
                                  entity, {'station': activity}))

    # ─────────────────────────────────────────────────────────────────────────
    # AllStations (FriendsGroup visits every station in queue-length order)
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_all_stations_next(self, event: Event) -> None:
        entity = event.entity
        eid    = entity.entity_id
        pending = self._pending_stations.get(eid, [])

        if not pending:
            self._push(make_event(self.clock, EventType.ALL_STATIONS_DONE, entity))
            return

        station_name = pending.pop(0)
        self._pending_stations[eid] = pending
        self._push(make_event(self.clock, EventType.STATION_QUEUE_JOIN,
                              entity, {'station': station_name,
                                       'all_stations_mode': True}))

    def _handle_all_stations_done(self, event: Event) -> None:
        entity = event.entity
        self._pending_stations.pop(entity.entity_id, None)
        # Notify FriendsGroup that this cycle of stations is done
        if isinstance(entity, FriendsGroup):
            entity.on_all_stations_done()
        self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)

    # ─────────────────────────────────────────────────────────────────────────
    # Stage handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_stage_queue_join(self, event: Event) -> None:
        """Entity arrives at a stage and either enters or joins the queue."""
        entity     = event.entity
        stage_name = event.data['stage']
        stage      = self.festival.stages[stage_name]

        # Festival day has ended – entity departs
        day_end = FESTIVAL_START + entity.day * DAY_DURATION
        if self.clock >= day_end:
            self._depart(entity)
            return

        if isinstance(stage, DJStage):
            if stage.enter(entity):
                # Entered immediately; schedule departure after sampled duration
                duration = stage.sample_stay_duration()
                self._sched(duration, EventType.STAGE_SHOW_END,
                            entity, {'stage': stage_name})
            else:
                # Full; join queue
                stage.enqueue(entity)
        else:
            # MainStage / SideStage
            if not stage.show_in_progress:
                # Show hasn't started yet; join queue (show start event pending)
                stage.enqueue(entity)
            else:
                # Show is ongoing; join queue (may enter if space opens)
                stage.enqueue(entity)
                # Try to admit immediately if space available
                admitted = stage.admit_from_queue()
                for e in admitted:
                    self._push(make_event(self.clock, EventType.STAGE_ENTER,
                                         e, {'stage': stage_name}))

    def _handle_stage_break_end(self, event: Event) -> None:
        """Inter-show break is over; start the next performance."""
        stage_name = event.data['stage']
        stage      = self.festival.stages[stage_name]
        day        = event.data.get('day', 1)
        day_end    = FESTIVAL_START + day * DAY_DURATION

        if self.clock >= day_end:
            return  # No more shows today

        # Sample duration for the new show
        duration = stage.sample_show_duration()
        show_end = self.clock + duration

        if show_end > day_end:
            show_end = day_end  # Truncate at festival end

        # Start the show; fill from queue
        admitted = stage.start_show(show_end)
        for entity in admitted:
            self._push(make_event(self.clock, EventType.STAGE_ENTER,
                                  entity, {'stage': stage_name}))

        # Schedule show end
        self._push(make_event(show_end, EventType.STAGE_SHOW_END,
                              None, {'stage': stage_name, 'day': day}))

    def _handle_stage_enter(self, event: Event) -> None:
        """
        Entity has entered a stage arena.

        For MainStage: the last 10 entities (back rows) each independently
        may leave 15 minutes after entry (probability 0.5).
        """
        entity     = event.entity
        stage_name = event.data['stage']
        stage      = self.festival.stages[stage_name]

        if stage_name == 'MainStage':
            back_row = stage.get_back_row_entities()
            if entity in back_row:
                # Schedule potential early leave
                self._sched(self.cfg.main_stage_early_leave_delay,
                            EventType.STAGE_EARLY_LEAVE,
                            entity, {'stage': stage_name})

    def _handle_stage_early_leave(self, event: Event) -> None:
        """Back-row entity may leave MainStage early (p=0.5)."""
        entity     = event.entity
        stage_name = event.data['stage']
        stage      = self.festival.stages[stage_name]

        if dist.sample_uniform_01() < self.cfg.main_stage_early_leave_prob:
            stage.remove_from_audience(entity)
            # Let other queued entities in
            admitted = stage.admit_from_queue()
            for e in admitted:
                self._push(make_event(self.clock, EventType.STAGE_ENTER,
                                      e, {'stage': stage_name}))
            # Entity moves on without satisfaction update (show incomplete)
            self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)

    def _handle_stage_show_end(self, event: Event) -> None:
        """A show ends: compute satisfaction for audience, clear arena."""
        stage_name = event.data.get('stage')
        day        = event.data.get('day', 1)
        entity     = event.entity   # None for scheduled stage events

        stage      = self.festival.stages[stage_name]

        if entity is not None:
            # This is a DJStage individual departure
            dj_stage = self.festival.dj_stage
            dj_stage.exit(entity)
            delta = dj_stage.compute_satisfaction_delta(self.clock)
            entity.update_satisfaction(delta)
            # Try to admit next in DJ queue
            while dj_stage.queue and dj_stage.available_capacity() > 0:
                next_e = dj_stage.queue.popleft()
                if dj_stage.enter(next_e):
                    dur = dj_stage.sample_stay_duration()
                    self._sched(dur, EventType.STAGE_SHOW_END,
                                next_e, {'stage': 'DJStage'})
            self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)
            return

        # MainStage / SideStage show ends
        audience = stage.end_show()
        for ent in audience:
            if not ent.departed:
                delta = stage.compute_satisfaction_delta(self.clock)
                ent.update_satisfaction(delta)
                # Notify entity type of show completion
                if isinstance(ent, Couple):
                    ent.on_show_completed()
                elif isinstance(ent, FriendsGroup):
                    ent.on_show_completed()
                ent.shows_attended.append(stage_name)
                self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, ent)

        # Schedule break then next show
        break_dur = stage.break_duration
        day_end   = FESTIVAL_START + day * DAY_DURATION
        next_show_start = self.clock + break_dur
        if next_show_start < day_end:
            self._push(make_event(next_show_start, EventType.STAGE_BREAK_END,
                                  None, {'stage': stage_name, 'day': day}))

    # ─────────────────────────────────────────────────────────────────────────
    # Service station handlers
    # Approach: no intermediate STATION_SERVICE_START event.
    # When a server is free on arrival → start immediately.
    # When service ends → release server and immediately serve next in queue.
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_station_queue_join(self, event: Event) -> None:
        """Entity arrives at a service station queue."""
        entity       = event.entity
        station_name = event.data['station']
        all_stations = event.data.get('all_stations_mode', False)
        station      = self.festival.get_station(station_name)

        if station is None:
            return

        if station.is_server_available():
            # Start service immediately — no queuing
            station.acquire_server()
            self.stats.record_queue_wait(station_name, 0.0)
            service_time = self._get_service_time(station_name, entity)
            self._push(make_event(self.clock + service_time,
                                  EventType.STATION_SERVICE_END,
                                  entity, {'station': station_name,
                                           'all_stations_mode': all_stations}))
        else:
            # All servers busy → join queue and schedule patience abandon
            station.enqueue(entity)
            entity.queue_join_time = self.clock
            patience = entity.get_patience()
            ab_event = make_event(self.clock + patience, EventType.STATION_ABANDON,
                                  entity, {'station': station_name,
                                           'all_stations_mode': all_stations})
            self._push(ab_event)
            self._abandon_events[entity.entity_id] = ab_event

    def _handle_station_service_start(self, event: Event) -> None:
        """Unused in current design; kept for dispatcher completeness."""
        pass  # Service start is now inlined in _handle_station_queue_join / _handle_station_service_end

    def _handle_station_service_end(self, event: Event) -> None:
        """Service completes; apply outcomes, release server, serve next."""
        station_name = event.data.get('station', '')
        all_stations = event.data.get('all_stations_mode', False)

        # Special case: BodyArt artist break end (no real entity)
        if station_name == 'BodyArt_break_end':
            artist_idx = event.data.get('artist_idx', 0)
            self.festival.body_art.artist_break_done(artist_idx)
            # Serve next entity if waiting and server now available
            ba = self.festival.body_art
            if ba.queue and ba.is_server_available():
                self._try_serve_next(ba, 'BodyArt')
            return

        entity  = event.entity
        station = self.festival.get_station(station_name)

        station.release_server()
        self._apply_station_outcome(station_name, entity)

        if isinstance(entity, Couple):
            entity.on_station_completed()

        # Serve the next valid entity waiting in the queue
        self._try_serve_next(station, station_name)

        if entity.departed:
            return

        self._after_station(entity, all_stations)

    def _handle_station_abandon(self, event: Event) -> None:
        """Entity patience exceeded; entity abandons queue."""
        entity       = event.entity
        station_name = event.data['station']
        all_stations = event.data.get('all_stations_mode', False)
        station      = self.festival.get_station(station_name)

        # Only act if entity is still registered as waiting
        if entity.entity_id not in self._abandon_events:
            return  # Entity already entered service → abandon event was cancelled

        del self._abandon_events[entity.entity_id]

        try:
            station.queue.remove(entity)
        except ValueError:
            return  # Entity was somehow already removed

        self.stats.record_abandonment(station_name)
        entity.update_satisfaction(-self._get_abandon_penalty(entity))

        if entity.departed:
            return

        if isinstance(entity, Couple):
            entity.on_station_completed()

        self._after_station(entity, all_stations)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers for station service
    # ─────────────────────────────────────────────────────────────────────────

    def _try_serve_next(self, station, station_name: str) -> None:
        """
        Pop the next valid (non-departed) entity from the queue and start service.
        Skips departed entities until a live one is found or queue is empty.
        """
        while station.queue:
            next_entity = station.queue.popleft()
            self._cancel_abandon(next_entity.entity_id)

            if next_entity.departed:
                continue  # Skip and try the next one

            # Start service for this entity
            station.acquire_server()
            wait = self.clock - (next_entity.queue_join_time or self.clock)
            self.stats.record_queue_wait(station_name, max(0.0, wait))
            next_entity.queue_join_time = None
            service_time = self._get_service_time(station_name, next_entity)
            self._push(make_event(self.clock + service_time,
                                  EventType.STATION_SERVICE_END,
                                  next_entity, {'station': station_name,
                                                'all_stations_mode': False}))
            break  # One entity served per released server

    def _after_station(self, entity: Entity, all_stations: bool) -> None:
        """Route entity after completing (or abandoning) a station."""
        if all_stations:
            eid     = entity.entity_id
            pending = self._pending_stations.get(eid, [])
            if pending:
                self._push(make_event(self.clock, EventType.ALL_STATIONS_NEXT,
                                      entity))
            else:
                self._push(make_event(self.clock, EventType.ALL_STATIONS_DONE,
                                      entity))
        else:
            self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)

    # ─────────────────────────────────────────────────────────────────────────
    # Food stall handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _send_to_food(self, entity: Entity) -> None:
        """Choose a restaurant and send entity to the food stall queue."""
        rest = dist.sample_food_restaurant(self.cfg.burger_prob, self.cfg.pizza_prob)
        station_name = f'FoodStall_{rest}'
        self._push(make_event(self.clock, EventType.FOOD_QUEUE_JOIN,
                              entity, {'station': station_name}))

    def _handle_food_queue_join(self, event: Event) -> None:
        station_name = event.data['station']
        entity       = event.entity
        station      = self.festival.get_station(station_name)

        station.enqueue(entity)
        entity.queue_join_time = self.clock

        if station.is_server_available():
            station.acquire_server()
            service_time = station.sample_order_service_time()
            self._push(make_event(self.clock + service_time,
                                  EventType.FOOD_SERVICE_END,
                                  entity, {'station': station_name}))

    def _handle_food_service_end(self, event: Event) -> None:
        """Order placed; entity receives food and starts eating."""
        station_name = event.data['station']
        entity       = event.entity
        station      = self.festival.get_station(station_name)

        station.release_server()

        # Record wait + spending
        wait = self.clock - (entity.queue_join_time or self.clock)
        self.stats.record_queue_wait(station_name, wait)
        cost = station.calculate_meal_cost(entity)
        entity.spending += cost

        # Apply satisfaction outcome
        station.process_outcome(entity)

        # Serve next in queue
        next_entity = station.dequeue()
        if next_entity is not None:
            station.acquire_server()
            svc = station.sample_order_service_time()
            self._push(make_event(self.clock + svc, EventType.FOOD_SERVICE_END,
                                  next_entity, {'station': station_name}))

        # Schedule eating time
        prep_time   = station.sample_prep_time()
        eating_time = station.sample_eating_time()
        self._sched(prep_time + eating_time, EventType.FOOD_EAT_END,
                    entity, {'station': station_name})

    def _handle_food_eat_end(self, event: Event) -> None:
        """Entity finishes eating; returns to activity flow."""
        entity = event.entity
        if not entity.departed:
            self._sched(0, EventType.ENTITY_NEXT_ACTIVITY, entity)

    # ─────────────────────────────────────────────────────────────────────────
    # Day end / overnight logic
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_day_end(self, event: Event) -> None:
        """End of a festival day; handle overnight decisions."""
        day = event.data['day']

        if day == 1:
            # Couples: decide overnight based on satisfaction
            # (We process entities that are still active — simplified by
            # tracking them in the statistics' entity_records is not needed here;
            # instead Couple.should_stay_overnight() was already checked
            # during routing — entities that would stay overnight are handled
            # by generating new Couple arrival events for day 2.)
            pass  # overnight arrivals already scheduled in _schedule_arrivals

        if day == 2:
            pass  # SIM_END will fire shortly

    def _handle_sim_end(self, event: Event) -> None:
        """Simulation complete; flush remaining entities."""
        pass  # RunStatistics already collected incrementally

    # ─────────────────────────────────────────────────────────────────────────
    # Departure
    # ─────────────────────────────────────────────────────────────────────────

    def _depart(self, entity: Entity) -> None:
        """Record entity departure and add to statistics."""
        if entity.departed:
            return
        entity.departed = True

        record = EntityRecord(
            entity_id          = entity.entity_id,
            entity_type        = entity.entity_type,
            size               = entity.size,
            day                = entity.day,
            arrival_time       = entity.arrival_time,
            depart_time        = self.clock,
            satisfaction       = entity.satisfaction,
            spending           = entity.spending,
            shows_attended     = list(entity.shows_attended),
            queue_abandonments = 0,  # simplified; tracked globally
            queue_waits        = {},
        )
        self.stats.record_entity(record)

    # ─────────────────────────────────────────────────────────────────────────
    # Helper utilities
    # ─────────────────────────────────────────────────────────────────────────

    def _cancel_abandon(self, entity_id: int) -> None:
        """Remove entity from pending-abandon registry (entity entered service)."""
        self._abandon_events.pop(entity_id, None)

    def _get_service_time(self, station_name: str, entity: Entity) -> float:
        """Dispatch to the correct station's service time sampler."""
        f  = self.festival
        sn = station_name
        if sn == 'EntryGate':        return f.entry_gate.sample_service_time()
        if sn == 'PhotoStation':     return f.photo_station.sample_service_time()
        if sn == 'ChargingStation':  return f.charging_station.sample_service_time()
        if sn == 'MerchTent':        return f.merch_tent.sample_service_time()
        if sn == 'BodyArt':
            idx = self._get_artist(entity)
            return f.body_art.sample_service_time(idx)
        return 1.0  # fallback

    def _apply_station_outcome(self, station_name: str, entity: Entity) -> None:
        """Apply post-service satisfaction / spending changes."""
        f = self.festival
        if station_name == 'PhotoStation':
            f.photo_station.process_outcome(entity)
        elif station_name == 'MerchTent':
            f.merch_tent.process_purchase(entity)
        elif station_name == 'BodyArt':
            idx = self._body_art_artist_map.pop(entity.entity_id, 0)
            needs_break = f.body_art.record_drawing_complete(idx)
            f.body_art.process_outcome(entity)
            if needs_break:
                f.body_art.artist_on_break[idx] = True
                # After the break the artist becomes available again.
                # We schedule a dummy service-end that just marks break as done.
                break_end_time = self.clock + self.cfg.body_art_break_duration
                self._push(make_event(break_end_time,
                                      EventType.STATION_SERVICE_END,
                                      None,
                                      {'station': 'BodyArt_break_end',
                                       'artist_idx': idx,
                                       'all_stations_mode': False}))

    def _get_artist(self, entity: Entity) -> int:
        """Assign (or retrieve) an available artist index for BodyArt."""
        eid = entity.entity_id
        if eid not in self._body_art_artist_map:
            # Find first available artist
            ba = self.festival.body_art
            for i in range(ba.num_servers):
                if not ba.artist_on_break[i]:
                    self._body_art_artist_map[eid] = i
                    break
            else:
                self._body_art_artist_map[eid] = 0  # fallback
        return self._body_art_artist_map[eid]

    def _get_abandon_penalty(self, entity: Entity) -> float:
        """Return the satisfaction penalty for queue abandonment."""
        if entity.entity_type == 'FriendsGroup':
            return self.cfg.friends_abandon_penalty
        elif entity.entity_type == 'Couple':
            return self.cfg.couple_abandon_penalty
        else:
            return self.cfg.single_abandon_penalty
