"""
engine.py
=========
Discrete-event simulation (DES) engine for Queuechella.

Architecture
------------
The engine keeps a priority queue (min-heap) called `event_diary`. The main
loop pops the earliest event, advances the clock, and calls event.handle(sim).
Each event class (defined in events.py) knows what to do — there is no
dispatcher in the engine.

This polymorphic style matches the example hotel-simulation project
distributed with the course.

Engine responsibilities:
1. Initialise stations, stages, statistics.
2. Schedule the seed events (arrivals, day-ends, sim end, first shows).
3. Run the main pop / handle loop.
4. Expose helper methods that events can call (routing, departures,
   service-time sampling, etc.).
"""

from __future__ import annotations

import heapq
import random
from typing import Dict, List, Optional, Set

from config import SimConfig, FESTIVAL_START, FESTIVAL_END, DAY_DURATION
import distributions as dist
from distributions import reset_box_muller
from entities import (
    Entity, FriendsGroup, Couple, Single,
    create_entity, reset_entity_counter
)
from events import (
    Event,
    EntityArriveEvent, EntryServiceEndEvent, EntityNextActivityEvent,
    StageQueueJoinEvent, StageEnterEvent, StageEarlyLeaveEvent,
    StageShowEndEvent, StageBreakEndEvent,
    StationQueueJoinEvent, StationServiceEndEvent, StationAbandonEvent,
    FoodQueueJoinEvent, FoodServiceEndEvent, FoodEatEndEvent,
    AllStationsNextEvent, AllStationsDoneEvent,
    DayEndEvent, SimEndEvent,
    reset_event_counter,
)
from stations import Festival, DJStage
from sim_stats import RunStatistics, EntityRecord


class Simulation:
    """
    Event-driven simulation engine.

    Usage:
        sim   = Simulation(cfg)
        stats = sim.run()
    """

    def __init__(self, cfg, friends_arrival_sampler=None,
                 main_stage_duration_sampler=None, verbose=False):
        self.cfg = cfg
        self.verbose = verbose

        # Distribution samplers (injected after fitting from Excel)
        self._friends_arrival = friends_arrival_sampler or self._default_friends_arrival
        self._main_stage_dur = main_stage_duration_sampler or (
            lambda: dist.sample_exponential(60.0))

        # Simulation state
        self.clock = 0.0
        self.event_diary: List[Event] = []         # min-heap of pending events
        self.festival = Festival(cfg)
        self.stats = RunStatistics()

        # Track entities currently waiting for a server (for abandonment)
        # entity_id -> StationAbandonEvent
        self._abandon_events: Dict[int, Event] = {}

        # Pending station list per FriendsGroup during AllStations tour
        self._pending_stations: Dict[int, List[str]] = {}

        # Body-art artist assignment per entity
        self._body_art_artist_map: Dict[int, int] = {}

        # Body-art art_type per entity (sampled at service start, reused
        # at outcome so duration and satisfaction refer to the same drawing)
        self._body_art_type_map: Dict[int, str] = {}

        # Live (non-departed) entities — used by DayEndEvent for overnight
        self._active_entities: Set[Entity] = set()

    # ─────────────────────────────────────────────────────────────────────────
    # Default samplers (placeholders until fitted from Excel)
    # ─────────────────────────────────────────────────────────────────────────

    def _default_friends_arrival(self):
        """FriendsGroup inter-arrival time (minutes). Exponential mean=5."""
        return dist.sample_exponential(5.0)

    # ─────────────────────────────────────────────────────────────────────────
    # Main run loop
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, seed=None):
        """Execute the full 2-day simulation and return collected statistics.

        Args:
            seed: Optional integer to seed the RNG (random.seed) so the run
                  is reproducible. Pass the same seed twice to get identical
                  results. Passing the same seed to two scenarios enables
                  Common Random Numbers (paired t-test becomes valid).
                  If None, the run uses the global RNG state and is NOT
                  reproducible.
        """
        if seed is not None:
            random.seed(seed)
        # Box-Muller caches a second variate between calls — drop it so a
        # cached value from a prior run can't leak past random.seed().
        reset_box_muller()

        reset_entity_counter()
        reset_event_counter()

        self.clock = FESTIVAL_START
        self.event_diary = []
        self.stats = RunStatistics()
        self._active_entities.clear()
        self._abandon_events.clear()
        self._pending_stations.clear()
        self._body_art_artist_map.clear()
        self._body_art_type_map.clear()

        # Re-create festival stations and inject the MainStage duration sampler
        self.festival = Festival(self.cfg)
        self.festival.set_main_stage_sampler(self._main_stage_dur)

        # Seed the event diary
        self._schedule_arrivals()
        self._schedule_show_starts()
        self._schedule_day_ends()
        self.schedule_event(
            SimEndEvent(FESTIVAL_START + 2 * DAY_DURATION))

        # ── The DES loop ──
        # Pop the next event, advance the clock, let the event handle itself.
        while self.event_diary:
            event = heapq.heappop(self.event_diary)
            self.clock = event.time
            if self.verbose:
                print("  t={:7.2f}  {}".format(self.clock, event))
            event.handle(self)

        return self.stats

    # ─────────────────────────────────────────────────────────────────────────
    # Public scheduling interface (used by event classes)
    # ─────────────────────────────────────────────────────────────────────────

    def schedule_event(self, event):
        """Push a pre-built Event onto the event diary."""
        heapq.heappush(self.event_diary, event)

    # ─────────────────────────────────────────────────────────────────────────
    # Seed events
    # ─────────────────────────────────────────────────────────────────────────

    def _schedule_arrivals(self):
        """Generate all entity arrivals for both festival days."""
        mult = self.cfg.arrival_rate_multiplier

        # FriendsGroup — Day 1, 09:00-13:00
        t = FESTIVAL_START
        fg_end = FESTIVAL_START + 4 * 60
        while t < fg_end:
            ia = self._friends_arrival() / mult
            t += ia
            if t >= fg_end:
                break
            self.schedule_event(EntityArriveEvent(t, 'FriendsGroup', 1))

        # Couples — Days 1+2, 10:00-16:00
        for day in (1, 2):
            day_start = FESTIVAL_START + (day - 1) * DAY_DURATION
            arr_start = day_start + 60
            arr_end = day_start + 7 * 60
            t = arr_start
            while t < arr_end:
                ia = dist.sample_exponential(
                    self.cfg.couple_arrival_rate_per_min) / mult
                t += ia
                if t >= arr_end:
                    break
                self.schedule_event(EntityArriveEvent(t, 'Couple', day))

        # Singles — Days 1+2, 09:00-16:00
        for day in (1, 2):
            day_start = FESTIVAL_START + (day - 1) * DAY_DURATION
            arr_end = day_start + 7 * 60
            t = day_start
            while t < arr_end:
                ia = dist.sample_exponential(
                    self.cfg.single_arrival_rate_per_min) / mult
                t += ia
                if t >= arr_end:
                    break
                self.schedule_event(EntityArriveEvent(t, 'Single', day))

    def _schedule_show_starts(self):
        """Schedule the first MainStage and SideStage shows for each day."""
        for day in (1, 2):
            day_start = FESTIVAL_START + (day - 1) * DAY_DURATION
            self.schedule_event(StageBreakEndEvent(day_start, 'MainStage', day))
            self.schedule_event(StageBreakEndEvent(day_start, 'SideStage', day))
            # DJStage runs continuously — no separate scheduling.

    def _schedule_day_ends(self):
        for day in (1, 2):
            t = FESTIVAL_START + day * DAY_DURATION
            self.schedule_event(DayEndEvent(t, day))

    # ─────────────────────────────────────────────────────────────────────────
    # Routing helpers (called by EntityNextActivityEvent.handle)
    # ─────────────────────────────────────────────────────────────────────────

    def _route_friends_group(self, entity):
        """FriendsGroup activity plan contains show names and an 'AllStations' sentinel."""
        activity = entity.next_activity()
        if activity is None:
            self._depart(entity)
        elif activity == 'AllStations':
            ordered = self.festival.ordered_stations_by_queue()
            self._pending_stations[entity.entity_id] = ordered
            self.schedule_event(AllStationsNextEvent(self.clock, entity))
        elif activity in ('MainStage', 'SideStage', 'DJStage'):
            self.schedule_event(
                StageQueueJoinEvent(self.clock, entity, activity))
        else:
            self.schedule_event(
                StationQueueJoinEvent(self.clock, entity, activity))

    def _route_couple(self, entity):
        """Couple alternates show <-> station; skips DJ stage."""
        activity = entity.next_activity()
        if activity is None:
            self._depart(entity)
        elif activity in ('MainStage', 'SideStage', 'DJStage'):
            if activity == 'DJStage':
                entity.on_show_completed()
                self.schedule_event(EntityNextActivityEvent(self.clock, entity))
            else:
                self.schedule_event(
                    StageQueueJoinEvent(self.clock, entity, activity))
        else:
            self.schedule_event(
                StationQueueJoinEvent(self.clock, entity, activity))

    def _route_single(self, entity):
        """Single follows a fixed activity plan."""
        activity = entity.next_activity()
        if activity is None:
            self._depart(entity)
        elif activity in ('MainStage', 'SideStage', 'DJStage'):
            self.schedule_event(
                StageQueueJoinEvent(self.clock, entity, activity))
        else:
            self.schedule_event(
                StationQueueJoinEvent(self.clock, entity, activity))

    def _after_station(self, entity, all_stations_mode):
        """Send entity to the next activity after a station visit."""
        if all_stations_mode:
            pending = self._pending_stations.get(entity.entity_id, [])
            if pending:
                self.schedule_event(AllStationsNextEvent(self.clock, entity))
            else:
                self.schedule_event(AllStationsDoneEvent(self.clock, entity))
        else:
            self.schedule_event(EntityNextActivityEvent(self.clock, entity))

    # ─────────────────────────────────────────────────────────────────────────
    # Service-station helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _try_serve_next(self, station, station_name):
        """Pop the next live entity from the queue and start their service.

        For BodyArt, an "available server" must be a non-break artist —
        a slot can be free (busy_servers < num_servers) while all remaining
        artists are on break. is_server_available() handles that distinction.
        """
        if not station.is_server_available():
            return  # No usable server right now — leave queue intact.

        while not station.queue.is_empty():
            next_entity = station.queue.pop(self.clock)
            self._cancel_abandon(next_entity.entity_id)
            if next_entity.departed:
                continue

            station.acquire_server()
            wait = self.clock - (next_entity.queue_join_time or self.clock)
            if wait < 0:
                wait = 0.0
            self.stats.record_queue_wait(station_name, wait)
            next_entity.queue_join_time = None

            service_time = self._get_service_time(station_name, next_entity)
            self.schedule_event(
                StationServiceEndEvent(self.clock + service_time,
                                       next_entity, station_name,
                                       all_stations_mode=False))
            break  # One entity per released server

    def _send_to_food(self, entity):
        """Send entity to a randomly chosen food stall."""
        rest = dist.sample_food_restaurant(self.cfg.burger_prob,
                                           self.cfg.pizza_prob)
        station_name = 'FoodStall_' + rest
        self.schedule_event(
            FoodQueueJoinEvent(self.clock, entity, station_name))

    def _get_service_time(self, station_name, entity):
        """Return service time for the given station / entity pair."""
        f = self.festival
        if station_name == 'EntryGate':
            return f.entry_gate.sample_service_time()
        if station_name == 'PhotoStation':
            return f.photo_station.sample_service_time()
        if station_name == 'ChargingStation':
            return f.charging_station.sample_service_time()
        if station_name == 'MerchTent':
            return f.merch_tent.sample_service_time()
        if station_name == 'BodyArt':
            idx = self._get_artist(entity)
            duration, art_type = f.body_art.sample_service_time(idx)
            self._body_art_type_map[entity.entity_id] = art_type
            return duration
        return 1.0  # fallback

    def _apply_station_outcome(self, station_name, entity):
        """Apply post-service satisfaction / spending side effects."""
        f = self.festival
        if station_name == 'PhotoStation':
            f.photo_station.process_outcome(entity)
        elif station_name == 'MerchTent':
            f.merch_tent.process_purchase(entity)
        elif station_name == 'BodyArt':
            idx = self._body_art_artist_map.pop(entity.entity_id, 0)
            art_type = self._body_art_type_map.pop(entity.entity_id, 'henna')
            needs_break = f.body_art.record_drawing_complete(idx)
            f.body_art.process_outcome(entity, art_type)
            if needs_break:
                # record_drawing_complete already marked the artist on break;
                # we just need to schedule the break-end event here.
                break_end_time = self.clock + self.cfg.body_art_break_duration
                self.schedule_event(
                    StationServiceEndEvent(break_end_time,
                                           entity=None,
                                           station_name='BodyArt_break_end',
                                           all_stations_mode=False,
                                           artist_idx=idx))

    def _get_artist(self, entity):
        """Assign or retrieve a body-art artist for the entity.

        The caller must have already confirmed that a free artist exists
        (via `is_server_available()`), so the loop is guaranteed to find one.
        """
        eid = entity.entity_id
        if eid not in self._body_art_artist_map:
            ba = self.festival.body_art
            for i in range(ba.num_servers):
                if not ba.artist_on_break[i]:
                    self._body_art_artist_map[eid] = i
                    break
            else:
                # Should be unreachable: BodyArtStation.is_server_available()
                # already excludes the "all artists on break" case.
                raise RuntimeError(
                    "No available BodyArt artist — is_server_available() "
                    "should have prevented this assignment.")
        return self._body_art_artist_map[eid]

    def _get_abandon_penalty(self, entity):
        """Satisfaction penalty for queue abandonment, by entity type."""
        if entity.entity_type == 'FriendsGroup':
            return self.cfg.friends_abandon_penalty
        elif entity.entity_type == 'Couple':
            return self.cfg.couple_abandon_penalty
        else:
            return self.cfg.single_abandon_penalty

    def _cancel_abandon(self, entity_id):
        """Remove entity from pending-abandon registry."""
        self._abandon_events.pop(entity_id, None)

    # ─────────────────────────────────────────────────────────────────────────
    # Departure
    # ─────────────────────────────────────────────────────────────────────────

    def _depart(self, entity):
        """Record entity departure into the statistics."""
        if entity.departed:
            return
        entity.departed = True
        self._active_entities.discard(entity)

        record = EntityRecord(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            size=entity.size,
            day=entity.day,
            arrival_time=entity.arrival_time,
            depart_time=self.clock,
            satisfaction=entity.satisfaction,
            spending=entity.spending,
            shows_attended=list(entity.shows_attended),
            queue_abandonments=0,
            queue_waits={},
        )
        self.stats.record_entity(record)
