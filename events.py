"""
events.py
=========
Polymorphic event classes for the discrete-event simulation.

Each event is a subclass of Event with its own handle(simulation) method.
The engine just pops events from the event_diary heap and calls
event.handle(simulation); the event itself knows how to update simulation
state and schedule follow-up events.

This mirrors the pattern used in the course example project (HotelSimulation),
which follows the polymorphic style introduced in Tutorial 6.

Event order in the heap: by (time, tie_break). The tie_break counter
ensures simultaneous events fire in insertion order.
"""

from __future__ import annotations

# Counter used when two events happen at the same time.
_event_counter = 0

# Returns a unique number for each event. Used to decide which event runs first when times are equal.
def _next_tie_break():
    global _event_counter
    _event_counter += 1
    return _event_counter


def reset_event_counter():
    """Reset the event counter before starting a new simulation run."""
    global _event_counter
    _event_counter = 0


# ─────────────────────────────────────────────────────────────────────────────
# Base Event class
# ─────────────────────────────────────────────────────────────────────────────

class Event:
    """
    Base class for all simulation events.

    Subclasses store any extra information they need as instance attributes
    and implement handle(simulation) to update simulation state.
    """

    def __init__(self, time, entity=None):
        # The simulation time when this event should happen.
        self.time = time

        # The entity related to this event.
        # Some events do not need an entity, so the default value is None.
        self.entity = entity

        # A unique number used when two events have the same time.
        self.tie_break = _next_tie_break()

    def __lt__(self, other):
        # This method tells Python how to compare two events in the heap.

        # First, events are sorted by their time.
        if self.time != other.time:
            return self.time < other.time

        # If two events have the same time,
        # the event that was created first will run first.
        return self.tie_break < other.tie_break

    def handle(self, simulation):
        # Every child class must write its own handle method.
        # If it does not, this error will be raised.
        raise NotImplementedError(
            self.__class__.__name__ + " must implement handle()")

    def __repr__(self):
        # Try to get the entity id.
        # If the event has no entity, use None.
        eid = getattr(self.entity, 'entity_id', None)

        # Return a readable text representation of the event.
        return "{}(t={:.2f}, entity={})".format(
            self.__class__.__name__, self.time, eid)


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle events
# ─────────────────────────────────────────────────────────────────────────────

class EntityArriveEvent(Event):
    """A new entity arrives at the festival entry gate."""

    def __init__(self, time, entity_type, day):
        # Initialize the basic event data from the parent class.
        super().__init__(time)

        # Save the type of entity that should be created.
        # For example: Single, Couple, FriendsGroup.
        self.entity_type = entity_type

        # Save the festival day (day 1 or day 2).
        self.day = day

    def handle(self, simulation):
        # Import here to avoid circular imports.
        from entities import create_entity

        # Create a new entity according to its type.
        entity = create_entity(
            self.entity_type,
            self.time,
            self.day,
            simulation.cfg
        )

        # Add the entity to the list of active entities in the simulation.
        simulation._active_entities.add(entity)

        # Get the festival entry gate.
        gate = simulation.festival.entry_gate

        # Add the entity to the entry queue.
        gate.enqueue(entity, simulation.clock)

        # Check if an entry server is available.
        if gate.is_server_available():

            # Reserve a server for this entity.
            gate.acquire_server()

            # Remove the entity from the queue immediately because
            # service starts right away and waiting time is zero.
            gate.dequeue(simulation.clock)

            # Sample how long the entry process will take.
            service_time = gate.sample_service_time()

            # Schedule the event that will happen when entry service ends.
            simulation.schedule_event(
                EntryServiceEndEvent(
                    simulation.clock + service_time,
                    entity
                )
            )


class EntryServiceEndEvent(Event):
    """Entry service done: entity enters festival, server may take next."""

    def handle(self, simulation):
        # Get the entity that finished the entry service.
        entity = self.entity

        # Get the festival entry gate.
        gate = simulation.festival.entry_gate

        # Mark that the entity has entered the festival.
        gate.process_entry(entity)

        # Release the entry server because this service is finished.
        gate.release_server()

        # Take the next entity from the entry queue, if there is one.
        next_entity = gate.dequeue(simulation.clock)

        # If another entity is waiting, start its entry service.
        if next_entity is not None:
            # Reserve the server for the next entity.
            gate.acquire_server()

            # Sample the service time for the next entity.
            service_time = gate.sample_service_time()

            # Schedule when the next entity will finish entry service.
            simulation.schedule_event(
                EntryServiceEndEvent(simulation.clock + service_time, next_entity))

        # Send the current entity to choose its next activity in the festival.
        simulation.schedule_event(EntityNextActivityEvent(simulation.clock, entity))


class EntityNextActivityEvent(Event):
    """Entity is free and picks its next activity."""

    def handle(self, simulation):
        # Import entity types used for routing.
        from entities import FriendsGroup, Couple, Single

        # Import distributions for random decisions.
        import distributions as dist

        # Import the festival start time.
        from config import FESTIVAL_START

        # Get the entity related to this event.
        entity = self.entity

        # If the entity already left the festival, do nothing.
        if entity.departed:
            return

        # Lunch check: the entity may go to a food stall during lunch time.
        if not getattr(entity, '_had_lunch', False):
            # Lunch window starts 4 hours after the festival starts.
            lunch_start = FESTIVAL_START + 4 * 60

            # Lunch window ends 6 hours after the festival starts.
            lunch_end = FESTIVAL_START + 6 * 60

            # Check if the current time is inside the lunch window.
            if lunch_start <= simulation.clock <= lunch_end:

                # Decide randomly if the entity goes to lunch.
                if dist.sample_uniform_01() < simulation.cfg.food_lunch_prob:

                    # Mark that this entity already had lunch.
                    entity._had_lunch = True

                    # Send the entity to a food station.
                    simulation._send_to_food(entity)

                    # Stop here because the next activity is food.
                    return

        # Route the entity according to its type.
        if isinstance(entity, FriendsGroup):
            # Friends groups use their own routing logic.
            simulation._route_friends_group(entity)

        elif isinstance(entity, Couple):
            # Couples use their own routing logic.
            simulation._route_couple(entity)

        elif isinstance(entity, Single):
            # Singles use their own routing logic.
            simulation._route_single(entity)


# ─────────────────────────────────────────────────────────────────────────────
# Stage events
# ─────────────────────────────────────────────────────────────────────────────

class StageQueueJoinEvent(Event):
    """Entity arrives at a stage and either enters or joins the queue."""

    def __init__(self, time, entity, stage_name):
        # Initialize the basic event data.
        super().__init__(time, entity)

        # Save the name of the stage the entity wants to visit.
        self.stage_name = stage_name

    def handle(self, simulation):
        # Import stage types and time constants only when needed.
        from stations import DJStage
        from config import FESTIVAL_START, DAY_DURATION

        # Get the entity and the relevant stage.
        entity = self.entity
        stage = simulation.festival.stages[self.stage_name]

        # Calculate the end time of the entity's festival day.
        day_end = FESTIVAL_START + entity.day * DAY_DURATION

        # If the day already ended, the entity leaves the festival.
        if simulation.clock >= day_end:
            simulation._depart(entity)
            return

        if isinstance(stage, DJStage):
            # DJ stage works continuously.
            # Entities enter one by one if there is available capacity.
            if stage.enter(entity):
                # Sample how long the entity will stay at the DJ stage.
                duration = stage.sample_stay_duration()

                # Schedule when the entity will leave the DJ stage.
                simulation.schedule_event(
                    StageShowEndEvent(simulation.clock + duration,
                                      stage_name=self.stage_name,
                                      entity=entity))
            else:
                # If the DJ stage is full, the entity joins the queue.
                stage.enqueue(entity, simulation.clock)
        else:
            # Main and Side stages work by shows.
            # The entity waits in the queue until the show admits it.
            stage.enqueue(entity, simulation.clock)

            # If a show is already in progress, try to admit entities now.
            if stage.show_in_progress:
                admitted = stage.admit_from_queue(simulation.clock)

                # Schedule entrance events for all admitted entities.
                for e in admitted:
                    simulation.schedule_event(
                        StageEnterEvent(simulation.clock, e, self.stage_name))


class StageEnterEvent(Event):
    """Entity entered a stage arena. Back-row entities get an early-leave check."""

    def __init__(self, time, entity, stage_name):
        # Initialize the basic event data.
        super().__init__(time, entity)

        # Save the stage name.
        self.stage_name = stage_name

    def handle(self, simulation):
        # Import MainStage to check if this is the main stage.
        from stations import MainStage

        # Get the entity and the relevant stage.
        entity = self.entity
        stage = simulation.festival.stages[self.stage_name]

        # Only MainStage has a back-row early leave option.
        if isinstance(stage, MainStage) and stage.is_back_row(entity):
            # Schedule a possible early leave after the delay time.
            simulation.schedule_event(
                StageEarlyLeaveEvent(simulation.clock + stage.early_leave_delay,
                                     entity, self.stage_name))


class StageEarlyLeaveEvent(Event):
    """Back-row entity may leave MainStage early (probability 0.5)."""

    def __init__(self, time, entity, stage_name):
        # Initialize the basic event data.
        super().__init__(time, entity)

        # Save the stage name.
        self.stage_name = stage_name

    def handle(self, simulation):
        # Get the entity and the relevant stage.
        entity = self.entity
        stage = simulation.festival.stages[self.stage_name]

        # Randomly decide if the entity leaves early.
        if stage.decides_to_leave_early():
            # Remove the entity from the audience.
            stage.remove_from_audience(entity)

            # Try to fill the empty place with entities from the queue.
            admitted = stage.admit_from_queue(simulation.clock)

            # Schedule entrance events for the new admitted entities.
            for e in admitted:
                simulation.schedule_event(
                    StageEnterEvent(simulation.clock, e, self.stage_name))

            # The entity did not finish the show,
            # so it continues to choose another activity.
            simulation.schedule_event(EntityNextActivityEvent(simulation.clock, entity))


class StageShowEndEvent(Event):
    """
    A show ends. Two sub-cases:
    - DJ stage individual departure (entity is set, stage_name='DJStage')
    - Main/Side stage end of performance (entity is None)
    """

    def __init__(self, time, stage_name, entity=None, day=1):
        # Initialize the basic event data.
        super().__init__(time, entity)

        # Save the stage name.
        self.stage_name = stage_name

        # Save the festival day.
        self.day = day

    def handle(self, simulation):
        # Import entity types that need special updates after a show.
        from entities import Couple, FriendsGroup

        # Import the festival start time.
        from config import FESTIVAL_START

        # Get the relevant stage.
        stage = simulation.festival.stages[self.stage_name]

        # Case 1: an individual entity leaves the DJ stage.
        if self.entity is not None:
            # Get the DJ stage object.
            dj_stage = simulation.festival.dj_stage

            # Remove the entity from the DJ stage.
            dj_stage.exit(self.entity)

            # Calculate and update the entity satisfaction.
            delta = dj_stage.compute_satisfaction_delta(simulation.clock)
            self.entity.update_satisfaction(delta)

            # Try to admit waiting entities while there is free capacity.
            while not dj_stage.queue.is_empty() and dj_stage.available_capacity() > 0:
                # Take the next entity from the DJ queue.
                next_e = dj_stage.queue.pop(simulation.clock)

                # If the entity enters successfully, schedule its leave time.
                if dj_stage.enter(next_e):
                    dur = dj_stage.sample_stay_duration()
                    simulation.schedule_event(
                        StageShowEndEvent(simulation.clock + dur,
                                          stage_name='DJStage',
                                          entity=next_e))

            # Send the current entity to choose the next activity.
            simulation.schedule_event(
                EntityNextActivityEvent(simulation.clock, self.entity))
            return

        # Case 2: a Main or Side stage show ends.
        audience = stage.end_show()

        # Update all entities that watched the show.
        for ent in audience:
            if not ent.departed:
                # Calculate and update satisfaction after the show.
                delta = stage.compute_satisfaction_delta(simulation.clock)
                ent.update_satisfaction(delta)

                # Couples and friends groups have special show-completion logic.
                if isinstance(ent, (Couple, FriendsGroup)):
                    ent.on_show_completed()

                # Save that this entity attended this stage.
                ent.shows_attended.append(self.stage_name)

                # Send the entity to choose the next activity.
                simulation.schedule_event(EntityNextActivityEvent(simulation.clock, ent))

        # Schedule the next show after the break, if the day is not over.
        day_end = FESTIVAL_START + self.day * 660  # DAY_DURATION
        next_show_start = simulation.clock + stage.break_duration

        # If there is still time in the day, schedule the end of the break.
        if next_show_start < day_end:
            simulation.schedule_event(
                StageBreakEndEvent(next_show_start, self.stage_name, self.day))


class StageBreakEndEvent(Event):
    """Inter-show break is over; start the next performance."""

    def __init__(self, time, stage_name, day):
        # Initialize the basic event data.
        super().__init__(time)

        # Save the stage name.
        self.stage_name = stage_name

        # Save the festival day.
        self.day = day

    def handle(self, simulation):
        # Import time constants.
        from config import FESTIVAL_START, DAY_DURATION

        # Get the relevant stage.
        stage = simulation.festival.stages[self.stage_name]

        # Calculate the end time of the festival day.
        day_end = FESTIVAL_START + self.day * DAY_DURATION

        # If the day already ended, do not start another show.
        if simulation.clock >= day_end:
            return

        # Sample the duration of the next show.
        duration = stage.sample_show_duration()
        show_end = simulation.clock + duration

        # If the show would end after the day ends, shorten it.
        if show_end > day_end:
            show_end = day_end

        # Start the show and admit entities from the queue.
        admitted = stage.start_show(show_end, simulation.clock)

        # Schedule entrance events for all admitted entities.
        for entity in admitted:
            simulation.schedule_event(
                StageEnterEvent(simulation.clock, entity, self.stage_name))

        # Schedule the end of the show.
        simulation.schedule_event(
            StageShowEndEvent(show_end, self.stage_name, day=self.day))

# ─────────────────────────────────────────────────────────────────────────────
# Service station events
# ─────────────────────────────────────────────────────────────────────────────

class StationQueueJoinEvent(Event):
    """Entity arrives at a service station queue."""

    def __init__(self, time, entity, station_name, all_stations_mode=False):
        super().__init__(time, entity)

        # Save the station name.
        self.station_name = station_name

        # True when the entity is visiting all stations in a special route.
        self.all_stations_mode = all_stations_mode

    def handle(self, simulation):
        # Get the entity and the station.
        entity = self.entity
        station = simulation.festival.get_station(self.station_name)

        # If the station does not exist, stop the event.
        if station is None:
            return

        if station.is_server_available():
            # If a server is free, service starts immediately.
            station.acquire_server()

            # Waiting time is zero because the entity did not wait.
            simulation.stats.record_queue_wait(self.station_name, 0.0)

            # Get the service time for this station and entity.
            service_time = simulation._get_service_time(self.station_name, entity)

            # Schedule when the service will end.
            simulation.schedule_event(
                StationServiceEndEvent(simulation.clock + service_time,
                                       entity, self.station_name,
                                       self.all_stations_mode))
        else:
            # If all servers are busy, the entity joins the queue.
            station.enqueue(entity, simulation.clock)

            # Save the time the entity joined the queue.
            entity.queue_join_time = simulation.clock

            # Get how long the entity is willing to wait.
            patience = entity.get_patience()

            # Create an abandonment event in case patience runs out.
            abandon = StationAbandonEvent(
                simulation.clock + patience, entity, self.station_name,
                self.all_stations_mode)

            # Schedule the abandonment event.
            simulation.schedule_event(abandon)

            # Save the abandonment event so it can be ignored later
            # if the entity starts service before abandoning.
            simulation._abandon_events[entity.entity_id] = abandon


class StationServiceEndEvent(Event):
    """Service at a station completes."""

    def __init__(self, time, entity, station_name, all_stations_mode=False,
                 artist_idx=None):
        super().__init__(time, entity)

        # Save the station name.
        self.station_name = station_name

        # True when this service is part of the all-stations route.
        self.all_stations_mode = all_stations_mode

        # Used only for BodyArt artist break-end events.
        self.artist_idx = artist_idx

    def handle(self, simulation):
        # Import Couple because couples need a special update.
        from entities import Couple

        # Special case: a BodyArt artist finished a break.
        if self.station_name == 'BodyArt_break_end':
            # Mark that the artist is back from break.
            simulation.festival.body_art.artist_break_done(self.artist_idx)

            # Get the BodyArt station.
            ba = simulation.festival.body_art

            # If someone is waiting and a server is free, start next service.
            if not ba.queue.is_empty() and ba.is_server_available():
                simulation._try_serve_next(ba, 'BodyArt')
            return

        # Get the entity and the station.
        entity = self.entity
        station = simulation.festival.get_station(self.station_name)

        # Release the server because service is finished.
        station.release_server()

        # Apply the result of the station service to the entity.
        simulation._apply_station_outcome(self.station_name, entity)

        # Couples need to update their internal state after a station.
        if isinstance(entity, Couple):
            entity.on_station_completed()

        # Try to serve the next entity in the queue.
        simulation._try_serve_next(station, self.station_name)

        # If the entity left the festival, stop here.
        if entity.departed:
            return

        # Decide what the entity should do after this station.
        simulation._after_station(entity, self.all_stations_mode)


class StationAbandonEvent(Event):
    """Entity gives up waiting and abandons the station queue."""

    def __init__(self, time, entity, station_name, all_stations_mode=False):
        super().__init__(time, entity)

        # Save the station name.
        self.station_name = station_name

        # True when this is part of the all-stations route.
        self.all_stations_mode = all_stations_mode

    def handle(self, simulation):
        # Import Couple because couples need a special update.
        from entities import Couple

        # Get the entity and the station.
        entity = self.entity
        station = simulation.festival.get_station(self.station_name)

        # If this entity is no longer registered for abandonment,
        # it means the entity already started service.
        # In that case, this old event should be ignored.
        if entity.entity_id not in simulation._abandon_events:
            return

        # Remove the abandonment registration.
        del simulation._abandon_events[entity.entity_id]

        # Try to remove the entity from the queue.
        if not station.queue.remove(entity, simulation.clock):
            return  # Entity was already removed somehow

        # Reduce satisfaction because the entity waited and left.
        entity.update_satisfaction(-simulation._get_abandon_penalty(entity))

        # If the entity left the festival, stop here.
        if entity.departed:
            return

        # Couples need to update their internal state after this station attempt.
        if isinstance(entity, Couple):
            entity.on_station_completed()

        # Decide what the entity should do next.
        simulation._after_station(entity, self.all_stations_mode)


# ─────────────────────────────────────────────────────────────────────────────
# Food events
# ─────────────────────────────────────────────────────────────────────────────

class FoodQueueJoinEvent(Event):
    """Entity arrives at a food stall."""

    def __init__(self, time, entity, station_name):
        super().__init__(time, entity)

        # Save the food station name.
        self.station_name = station_name

    def handle(self, simulation):
        # Get the entity and the food station.
        entity = self.entity
        station = simulation.festival.get_station(self.station_name)

        if station.is_server_available():
            # If a server is free, ordering starts immediately.
            station.acquire_server()

            # Waiting time is zero.
            simulation.stats.record_queue_wait(self.station_name, 0.0)

            # Sample the order service time.
            service_time = station.sample_order_service_time()

            # Schedule when the order service will end.
            simulation.schedule_event(
                FoodServiceEndEvent(simulation.clock + service_time,
                                    entity, self.station_name))
        else:
            # If all servers are busy, the entity joins the queue.
            station.enqueue(entity, simulation.clock)

            # Save the time the entity joined the queue.
            entity.queue_join_time = simulation.clock


class FoodServiceEndEvent(Event):
    """Order placed; entity receives food and starts eating."""

    def __init__(self, time, entity, station_name):
        super().__init__(time, entity)

        # Save the food station name.
        self.station_name = station_name

    def handle(self, simulation):
        # Get the entity and the food station.
        entity = self.entity
        station = simulation.festival.get_station(self.station_name)

        # Release the food server because ordering is finished.
        station.release_server()

        # Charge the meal cost and update the entity result.
        station.charge_meal(entity)
        station.process_outcome(entity)

        # Serve the next entity in the food queue, if there is one.
        next_entity = station.dequeue(simulation.clock)

        if next_entity is not None:
            # Reserve the server for the next entity.
            station.acquire_server()

            # Calculate the waiting time of the next entity.
            wait = simulation.clock - (next_entity.queue_join_time or simulation.clock)

            # Avoid negative waiting time.
            if wait < 0:
                wait = 0.0

            # Record the waiting time.
            simulation.stats.record_queue_wait(self.station_name, wait)

            # Clear the queue join time.
            next_entity.queue_join_time = None

            # Sample the next order service time.
            svc = station.sample_order_service_time()

            # Schedule when the next order service will end.
            simulation.schedule_event(
                FoodServiceEndEvent(simulation.clock + svc,
                                    next_entity, self.station_name))

        # Sample preparation time and eating time.
        prep_time = station.sample_prep_time()
        eating_time = station.sample_eating_time()

        # Schedule when the entity will finish eating.
        simulation.schedule_event(
            FoodEatEndEvent(simulation.clock + prep_time + eating_time,
                            entity, self.station_name))


class FoodEatEndEvent(Event):
    """Entity finishes eating and returns to the activity flow."""

    def __init__(self, time, entity, station_name):
        super().__init__(time, entity)

        # Save the food station name.
        self.station_name = station_name

    def handle(self, simulation):
        # If the entity is still in the festival,
        # send it to choose the next activity.
        if not self.entity.departed:
            simulation.schedule_event(EntityNextActivityEvent(simulation.clock, self.entity))


# ─────────────────────────────────────────────────────────────────────────────
# FriendsGroup "AllStations" tour events
# ─────────────────────────────────────────────────────────────────────────────

class AllStationsNextEvent(Event):
    """FriendsGroup picks the next shortest-queue station to visit."""

    def handle(self, simulation):
        # Get the friends group entity.
        entity = self.entity

        # Get the list of stations still waiting to be visited.
        pending = simulation._pending_stations.get(entity.entity_id, [])

        # If there are no more stations, the tour is done.
        if not pending:
            simulation.schedule_event(AllStationsDoneEvent(simulation.clock, entity))
            return

        # Take the next station from the list.
        station_name = pending.pop(0)

        # Save the updated pending station list.
        simulation._pending_stations[entity.entity_id] = pending

        # Send the entity to the next station.
        simulation.schedule_event(
            StationQueueJoinEvent(simulation.clock, entity, station_name,
                                  all_stations_mode=True))


class AllStationsDoneEvent(Event):
    """FriendsGroup has visited every station for one cycle."""

    def handle(self, simulation):
        # Import FriendsGroup because only friends groups use this logic.
        from entities import FriendsGroup

        # Get the entity.
        entity = self.entity

        # Remove the pending stations list for this entity.
        simulation._pending_stations.pop(entity.entity_id, None)

        # Update the friends group state after finishing all stations.
        if isinstance(entity, FriendsGroup):
            entity.on_all_stations_done()

        # Send the entity to choose the next activity.
        simulation.schedule_event(EntityNextActivityEvent(simulation.clock, entity))


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

        # Save the festival day that is ending.
        self.day = day

    def handle(self, simulation):
        # Import entity types that have special end-of-day rules.
        from entities import Couple, FriendsGroup

        # Go over a copy of the active entities list.
        # A copy is used because entities may leave during this loop.
        for entity in list(simulation._active_entities):

            # Ignore entities that already left or belong to another day.
            if entity.departed or entity.day != self.day:
                continue

            if self.day == 1:
                # On day 1, some entities may stay overnight.

                if isinstance(entity, Couple):
                    # Couples decide whether to stay overnight.
                    if entity.should_stay_overnight():
                        # Charge overnight cost and move the couple to day 2.
                        simulation.festival.charge_overnight(entity)
                        entity.day = 2
                    else:
                        # If the couple does not stay, it leaves.
                        simulation._depart(entity)

                elif isinstance(entity, FriendsGroup):
                    # Friends groups may already have a stay decision.
                    if entity.stays_overnight:
                        # Move the group to day 2.
                        entity.day = 2
                    else:
                        # If the group does not stay, it leaves.
                        simulation._depart(entity)

                else:  # Single
                    # Singles leave at the end of day 1.
                    simulation._depart(entity)

            else:  # day == 2
                # At the end of day 2, all remaining entities leave.
                simulation._depart(entity)


class SimEndEvent(Event):
    """Simulation finished. Nothing to do; RunStatistics is collected
    incrementally during the run."""

    def handle(self, simulation):
        # Nothing needs to happen here.
        # Statistics were already collected during the simulation.
        pass