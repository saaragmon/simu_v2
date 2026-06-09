"""
events.py
=========
Polymorphic event classes for the discrete-event simulation.

Each event is a subclass of Event with its own handle(sim) method.
The engine just pops events from the event_diary heap and calls
event.handle(sim); the event itself knows how to update simulation
state and schedule follow-up events.

This mirrors the pattern used in the course example project (HotelSimulation),
which follows the polymorphic style introduced in Tutorial 6.

Event order in the heap: by (time, tie_break). The tie_break counter
ensures simultaneous events fire in insertion order.
"""

from __future__ import annotations

# Module-level counter used to break ties between simultaneous events.
_event_counter = 0


def _next_tie_break():
    global _event_counter
    _event_counter += 1
    return _event_counter


def reset_event_counter():
    """Reset the global tie-break counter (call before each simulation run)."""
    global _event_counter
    _event_counter = 0


# ─────────────────────────────────────────────────────────────────────────────
# Base Event class
# ─────────────────────────────────────────────────────────────────────────────

class Event:
    """
    Base class for all simulation events.

    Subclasses store any extra information they need as instance attributes
    and implement handle(sim) to update simulation state.
    """

    def __init__(self, time, entity=None):
        self.time = time
        self.entity = entity
        self.tie_break = _next_tie_break()

    def __lt__(self, other):
        # The heap sorts events by time, then by insertion order.
        if self.time != other.time:
            return self.time < other.time
        return self.tie_break < other.tie_break

    def handle(self, sim):
        raise NotImplementedError(
            self.__class__.__name__ + " must implement handle()")

    def __repr__(self):
        eid = getattr(self.entity, 'entity_id', None)
        return "{}(t={:.2f}, entity={})".format(
            self.__class__.__name__, self.time, eid)


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle events
# ─────────────────────────────────────────────────────────────────────────────

class EntityArriveEvent(Event):
    """A new entity arrives at the festival entry gate."""

    def __init__(self, time, entity_type, day):
        super().__init__(time)
        self.entity_type = entity_type
        self.day = day

    def handle(self, sim):
        from entities import create_entity
        entity = create_entity(self.entity_type, self.time, self.day, sim.cfg)
        sim._active_entities.add(entity)

        gate = sim.festival.entry_gate
        gate.enqueue(entity)

        if gate.is_server_available():
            gate.acquire_server()
            service_time = gate.sample_service_time()
            sim.schedule_event(
                EntryServiceEndEvent(sim.clock + service_time, entity))


class EntryServiceEndEvent(Event):
    """Entry service done: entity enters festival, server may take next."""

    def handle(self, sim):
        from entities import FriendsGroup
        entity = self.entity
        gate = sim.festival.entry_gate

        # Pay entry ticket (overnight pre-decided for FriendsGroup)
        has_overnight = False
        if isinstance(entity, FriendsGroup) and entity.stays_overnight:
            has_overnight = True
        entity.pay_entry(has_overnight)
        sim.stats.total_revenue += entity.spending

        gate.release_server()

        # Serve next entity in queue
        next_entity = gate.dequeue()
        if next_entity is not None:
            gate.acquire_server()
            service_time = gate.sample_service_time()
            sim.schedule_event(
                EntryServiceEndEvent(sim.clock + service_time, next_entity))

        # Send the entity into the festival
        sim.schedule_event(EntityNextActivityEvent(sim.clock, entity))


class EntityNextActivityEvent(Event):
    """Entity is free and picks its next activity."""

    def handle(self, sim):
        from entities import FriendsGroup, Couple, Single
        import distributions_delete as dist
        from config import FESTIVAL_START

        entity = self.entity
        if entity.departed:
            return

        # Lunch check: optional detour to a food stall during the lunch window
        if not getattr(entity, '_had_lunch', False):
            lunch_start = FESTIVAL_START + 4 * 60
            lunch_end = FESTIVAL_START + 6 * 60
            if lunch_start <= sim.clock <= lunch_end:
                if dist.sample_uniform_01() < sim.cfg.food_lunch_prob:
                    entity._had_lunch = True
                    sim._send_to_food(entity)
                    return

        # Routing by entity type
        if isinstance(entity, FriendsGroup):
            sim._route_friends_group(entity)
        elif isinstance(entity, Couple):
            sim._route_couple(entity)
        elif isinstance(entity, Single):
            sim._route_single(entity)


# ─────────────────────────────────────────────────────────────────────────────
# Stage events
# ─────────────────────────────────────────────────────────────────────────────

class StageQueueJoinEvent(Event):
    """Entity arrives at a stage and either enters or joins the queue."""

    def __init__(self, time, entity, stage_name):
        super().__init__(time, entity)
        self.stage_name = stage_name

    def handle(self, sim):
        from stations import DJStage
        from config import FESTIVAL_START, DAY_DURATION

        entity = self.entity
        stage = sim.festival.stages[self.stage_name]

        # Festival day has ended for this entity → depart now
        day_end = FESTIVAL_START + entity.day * DAY_DURATION
        if sim.clock >= day_end:
            sim._depart(entity)
            return

        if isinstance(stage, DJStage):
            # DJ stage runs continuously; entities enter individually
            if stage.enter(entity):
                duration = stage.sample_stay_duration()
                sim.schedule_event(
                    StageShowEndEvent(sim.clock + duration,
                                      stage_name=self.stage_name,
                                      entity=entity))
            else:
                stage.enqueue(entity)
        else:
            # Main / Side stage: queue until the next show admits us
            stage.enqueue(entity)
            if stage.show_in_progress:
                admitted = stage.admit_from_queue()
                for e in admitted:
                    sim.schedule_event(
                        StageEnterEvent(sim.clock, e, self.stage_name))


class StageEnterEvent(Event):
    """Entity entered a stage arena. Back-row entities get an early-leave check."""

    def __init__(self, time, entity, stage_name):
        super().__init__(time, entity)
        self.stage_name = stage_name

    def handle(self, sim):
        entity = self.entity
        stage = sim.festival.stages[self.stage_name]

        if self.stage_name == 'MainStage':
            back_row = stage.get_back_row_entities()
            if entity in back_row:
                # Schedule a possible early leave 15 min after entry
                delay = sim.cfg.main_stage_early_leave_delay
                sim.schedule_event(
                    StageEarlyLeaveEvent(sim.clock + delay,
                                         entity, self.stage_name))


class StageEarlyLeaveEvent(Event):
    """Back-row entity may leave MainStage early (probability 0.5)."""

    def __init__(self, time, entity, stage_name):
        super().__init__(time, entity)
        self.stage_name = stage_name

    def handle(self, sim):
        import distributions_delete as dist

        entity = self.entity
        stage = sim.festival.stages[self.stage_name]

        if dist.sample_uniform_01() < sim.cfg.main_stage_early_leave_prob:
            stage.remove_from_audience(entity)
            # Pull replacements from queue
            admitted = stage.admit_from_queue()
            for e in admitted:
                sim.schedule_event(
                    StageEnterEvent(sim.clock, e, self.stage_name))
            # Entity moves on without satisfaction update (didn't finish show)
            sim.schedule_event(EntityNextActivityEvent(sim.clock, entity))


class StageShowEndEvent(Event):
    """
    A show ends. Two sub-cases:
    - DJ stage individual departure (entity is set, stage_name='DJStage')
    - Main/Side stage end of performance (entity is None)
    """

    def __init__(self, time, stage_name, entity=None, day=1):
        super().__init__(time, entity)
        self.stage_name = stage_name
        self.day = day

    def handle(self, sim):
        from entities import Couple, FriendsGroup
        from config import FESTIVAL_START

        stage = sim.festival.stages[self.stage_name]

        # Case 1: individual departure from DJ stage
        if self.entity is not None:
            dj_stage = sim.festival.dj_stage
            dj_stage.exit(self.entity)
            delta = dj_stage.compute_satisfaction_delta(sim.clock)
            self.entity.update_satisfaction(delta)

            # Try to admit waiting entities
            while dj_stage.queue and dj_stage.available_capacity() > 0:
                next_e = dj_stage.queue.popleft()
                if dj_stage.enter(next_e):
                    dur = dj_stage.sample_stay_duration()
                    sim.schedule_event(
                        StageShowEndEvent(sim.clock + dur,
                                          stage_name='DJStage',
                                          entity=next_e))
            sim.schedule_event(
                EntityNextActivityEvent(sim.clock, self.entity))
            return

        # Case 2: Main / Side stage end of show
        audience = stage.end_show()
        for ent in audience:
            if not ent.departed:
                delta = stage.compute_satisfaction_delta(sim.clock)
                ent.update_satisfaction(delta)
                if isinstance(ent, (Couple, FriendsGroup)):
                    ent.on_show_completed()
                ent.shows_attended.append(self.stage_name)
                sim.schedule_event(EntityNextActivityEvent(sim.clock, ent))

        # Schedule next show start (after break) if still within day
        day_end = FESTIVAL_START + self.day * 660  # DAY_DURATION
        next_show_start = sim.clock + stage.break_duration
        if next_show_start < day_end:
            sim.schedule_event(
                StageBreakEndEvent(next_show_start, self.stage_name, self.day))


class StageBreakEndEvent(Event):
    """Inter-show break is over; start the next performance."""

    def __init__(self, time, stage_name, day):
        super().__init__(time)
        self.stage_name = stage_name
        self.day = day

    def handle(self, sim):
        from config import FESTIVAL_START, DAY_DURATION

        stage = sim.festival.stages[self.stage_name]
        day_end = FESTIVAL_START + self.day * DAY_DURATION

        if sim.clock >= day_end:
            return  # No more shows today

        # Sample new show duration
        duration = stage.sample_show_duration()
        show_end = sim.clock + duration
        if show_end > day_end:
            show_end = day_end

        # Start the show and admit from queue
        admitted = stage.start_show(show_end)
        for entity in admitted:
            sim.schedule_event(
                StageEnterEvent(sim.clock, entity, self.stage_name))

        # Schedule the show end
        sim.schedule_event(
            StageShowEndEvent(show_end, self.stage_name, day=self.day))


# ─────────────────────────────────────────────────────────────────────────────
# Service station events
# ─────────────────────────────────────────────────────────────────────────────

class StationQueueJoinEvent(Event):
    """Entity arrives at a service station queue."""

    def __init__(self, time, entity, station_name, all_stations_mode=False):
        super().__init__(time, entity)
        self.station_name = station_name
        self.all_stations_mode = all_stations_mode

    def handle(self, sim):
        entity = self.entity
        station = sim.festival.get_station(self.station_name)
        if station is None:
            return

        if station.is_server_available():
            # Start service immediately
            station.acquire_server()
            sim.stats.record_queue_wait(self.station_name, 0.0)
            service_time = sim._get_service_time(self.station_name, entity)
            sim.schedule_event(
                StationServiceEndEvent(sim.clock + service_time,
                                       entity, self.station_name,
                                       self.all_stations_mode))
        else:
            # All servers busy: join queue, schedule patience abandonment
            station.enqueue(entity)
            entity.queue_join_time = sim.clock
            patience = entity.get_patience()
            abandon = StationAbandonEvent(
                sim.clock + patience, entity, self.station_name,
                self.all_stations_mode)
            sim.schedule_event(abandon)
            sim._abandon_events[entity.entity_id] = abandon


class StationServiceEndEvent(Event):
    """Service at a station completes."""

    def __init__(self, time, entity, station_name, all_stations_mode=False,
                 artist_idx=None):
        super().__init__(time, entity)
        self.station_name = station_name
        self.all_stations_mode = all_stations_mode
        self.artist_idx = artist_idx  # Used only for BodyArt break-end events

    def handle(self, sim):
        from entities import Couple

        # Special: BodyArt artist break-end (entity is None)
        if self.station_name == 'BodyArt_break_end':
            sim.festival.body_art.artist_break_done(self.artist_idx)
            ba = sim.festival.body_art
            if ba.queue and ba.is_server_available():
                sim._try_serve_next(ba, 'BodyArt')
            return

        entity = self.entity
        station = sim.festival.get_station(self.station_name)

        station.release_server()
        sim._apply_station_outcome(self.station_name, entity)

        if isinstance(entity, Couple):
            entity.on_station_completed()

        sim._try_serve_next(station, self.station_name)

        if entity.departed:
            return

        sim._after_station(entity, self.all_stations_mode)


class StationAbandonEvent(Event):
    """Entity gives up waiting and abandons the station queue."""

    def __init__(self, time, entity, station_name, all_stations_mode=False):
        super().__init__(time, entity)
        self.station_name = station_name
        self.all_stations_mode = all_stations_mode

    def handle(self, sim):
        from entities import Couple

        entity = self.entity
        station = sim.festival.get_station(self.station_name)

        # If the abandon registration is gone, the entity already entered
        # service before patience ran out → ignore this stale event.
        if entity.entity_id not in sim._abandon_events:
            return

        del sim._abandon_events[entity.entity_id]

        try:
            station.queue.remove(entity)
        except ValueError:
            return  # Entity was already removed somehow

        sim.stats.record_abandonment(self.station_name)
        entity.update_satisfaction(-sim._get_abandon_penalty(entity))

        if entity.departed:
            return

        if isinstance(entity, Couple):
            entity.on_station_completed()

        sim._after_station(entity, self.all_stations_mode)


# ─────────────────────────────────────────────────────────────────────────────
# Food events
# ─────────────────────────────────────────────────────────────────────────────

class FoodQueueJoinEvent(Event):
    """Entity arrives at a food stall."""

    def __init__(self, time, entity, station_name):
        super().__init__(time, entity)
        self.station_name = station_name

    def handle(self, sim):
        entity = self.entity
        station = sim.festival.get_station(self.station_name)

        if station.is_server_available():
            station.acquire_server()
            sim.stats.record_queue_wait(self.station_name, 0.0)
            service_time = station.sample_order_service_time()
            sim.schedule_event(
                FoodServiceEndEvent(sim.clock + service_time,
                                    entity, self.station_name))
        else:
            station.enqueue(entity)
            entity.queue_join_time = sim.clock


class FoodServiceEndEvent(Event):
    """Order placed; entity receives food and starts eating."""

    def __init__(self, time, entity, station_name):
        super().__init__(time, entity)
        self.station_name = station_name

    def handle(self, sim):
        entity = self.entity
        station = sim.festival.get_station(self.station_name)

        station.release_server()

        # Charge meal cost and apply satisfaction outcome
        cost = station.calculate_meal_cost(entity)
        entity.spending += cost
        station.process_outcome(entity)

        # Serve next in queue
        next_entity = station.dequeue()
        if next_entity is not None:
            station.acquire_server()
            wait = sim.clock - (next_entity.queue_join_time or sim.clock)
            if wait < 0:
                wait = 0.0
            sim.stats.record_queue_wait(self.station_name, wait)
            next_entity.queue_join_time = None
            svc = station.sample_order_service_time()
            sim.schedule_event(
                FoodServiceEndEvent(sim.clock + svc,
                                    next_entity, self.station_name))

        # Schedule eating time for the entity that just finished service
        prep_time = station.sample_prep_time()
        eating_time = station.sample_eating_time()
        sim.schedule_event(
            FoodEatEndEvent(sim.clock + prep_time + eating_time,
                            entity, self.station_name))


class FoodEatEndEvent(Event):
    """Entity finishes eating and returns to the activity flow."""

    def __init__(self, time, entity, station_name):
        super().__init__(time, entity)
        self.station_name = station_name

    def handle(self, sim):
        if not self.entity.departed:
            sim.schedule_event(EntityNextActivityEvent(sim.clock, self.entity))


# ─────────────────────────────────────────────────────────────────────────────
# FriendsGroup "AllStations" tour events
# ─────────────────────────────────────────────────────────────────────────────

class AllStationsNextEvent(Event):
    """FriendsGroup picks the next shortest-queue station to visit."""

    def handle(self, sim):
        entity = self.entity
        pending = sim._pending_stations.get(entity.entity_id, [])

        if not pending:
            sim.schedule_event(AllStationsDoneEvent(sim.clock, entity))
            return

        station_name = pending.pop(0)
        sim._pending_stations[entity.entity_id] = pending
        sim.schedule_event(
            StationQueueJoinEvent(sim.clock, entity, station_name,
                                  all_stations_mode=True))


class AllStationsDoneEvent(Event):
    """FriendsGroup has visited every station for one cycle."""

    def handle(self, sim):
        from entities import FriendsGroup
        entity = self.entity
        sim._pending_stations.pop(entity.entity_id, None)
        if isinstance(entity, FriendsGroup):
            entity.on_all_stations_done()
        sim.schedule_event(EntityNextActivityEvent(sim.clock, entity))


# ─────────────────────────────────────────────────────────────────────────────
# Global events
# ─────────────────────────────────────────────────────────────────────────────

class DayEndEvent(Event):
    """
    End of a festival day.
    Day 1: decide overnight stays per entity.
    Day 2: force-depart anyone still in the system before SIM_END.
    """

    def __init__(self, time, day):
        super().__init__(time)
        self.day = day

    def handle(self, sim):
        from entities import Couple, FriendsGroup

        for entity in list(sim._active_entities):
            if entity.departed or entity.day != self.day:
                continue

            if self.day == 1:
                if isinstance(entity, Couple):
                    if entity.should_stay_overnight():
                        overnight_fee = sim.cfg.overnight_price * entity.size
                        entity.spending += overnight_fee
                        sim.stats.total_revenue += overnight_fee
                        entity.day = 2
                        sim.stats.num_overnight += 1
                    else:
                        sim._depart(entity)
                elif isinstance(entity, FriendsGroup):
                    if entity.stays_overnight:
                        entity.day = 2
                        sim.stats.num_overnight += 1
                    else:
                        sim._depart(entity)
                else:  # Single
                    sim._depart(entity)
            else:  # day == 2
                sim._depart(entity)


class SimEndEvent(Event):
    """Simulation finished. Nothing to do; RunStatistics is collected
    incrementally during the run."""

    def handle(self, sim):
        pass
