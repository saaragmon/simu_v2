"""
events.py
=========
Event type definitions for the discrete-event simulation.

An Event is a lightweight named-tuple that is pushed onto the priority queue.
The engine compares events by (time, tie_break) so that simultaneous events
have a deterministic ordering.

Event types:
    ENTITY_ARRIVE         – new entity arrives at the festival entry gate
    ENTRY_SERVICE_END     – ticket scan + security check complete; entity enters festival
    ENTITY_NEXT_ACTIVITY  – entity is free and picks its next activity
    STAGE_QUEUE_JOIN      – entity joins a stage queue (waiting for next show)
    STAGE_ENTER           – entity enters a stage (show started / space opened)
    STAGE_EARLY_LEAVE     – entity in back rows of MainStage leaves early
    STAGE_SHOW_END        – a show at a stage finishes; audience exits
    STAGE_BREAK_END       – inter-show break is over; next show can start
    STATION_QUEUE_JOIN    – entity joins a service station queue
    STATION_ABANDON       – entity abandons a station queue (patience exceeded)
    STATION_SERVICE_END   – service at a station completes
    FOOD_QUEUE_JOIN       – entity joins food stall queue
    FOOD_SERVICE_END      – food ordered; entity starts eating
    FOOD_EAT_END          – entity finishes eating; returns to activity flow
    ALL_STATIONS_NEXT     – FriendsGroup picks next shortest-queue station
    ALL_STATIONS_DONE     – FriendsGroup has visited all stations in one round
    DAY_END               – end of a festival day; overnight decisions made
    SIM_END               – simulation complete
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class EventType(Enum):
    ENTITY_ARRIVE         = auto()
    ENTRY_SERVICE_END     = auto()
    ENTITY_NEXT_ACTIVITY  = auto()
    STAGE_QUEUE_JOIN      = auto()
    STAGE_ENTER           = auto()
    STAGE_EARLY_LEAVE     = auto()
    STAGE_SHOW_END        = auto()
    STAGE_BREAK_END       = auto()
    STATION_QUEUE_JOIN    = auto()
    STATION_ABANDON       = auto()
    STATION_SERVICE_END   = auto()
    FOOD_QUEUE_JOIN       = auto()
    FOOD_SERVICE_END      = auto()
    FOOD_EAT_END          = auto()
    ALL_STATIONS_NEXT     = auto()
    ALL_STATIONS_DONE     = auto()
    DAY_END               = auto()
    SIM_END               = auto()


_event_counter = 0  # For deterministic tie-breaking


@dataclass(order=True)
class Event:
    """
    A single simulation event.

    Fields are ordered for heap comparison: (time, tie_break) ensures
    events at the same clock time are processed in insertion order.

    Attributes:
        time       : Simulation clock time (minutes from midnight).
        tie_break  : Auto-incrementing counter for deterministic ordering.
        event_type : One of the EventType enum values.
        entity     : The entity associated with this event (may be None for
                     global events like DAY_END).
        data       : Optional payload dict for event-specific information
                     (e.g. station name, show genre, etc.).
    """
    time:       float
    tie_break:  int       = field(compare=True, default_factory=lambda: 0)
    event_type: EventType = field(compare=False, default=EventType.SIM_END)
    entity:     Any       = field(compare=False, default=None)
    data:       dict      = field(compare=False, default_factory=dict)

    def __repr__(self) -> str:
        eid = getattr(self.entity, 'entity_id', None)
        return (f"Event(t={self.time:.2f}, {self.event_type.name}, "
                f"entity={eid}, data={self.data})")


def make_event(time: float,
               event_type: EventType,
               entity: Any = None,
               data: Optional[dict] = None) -> Event:
    """
    Convenience constructor that auto-assigns the tie_break counter.

    Args:
        time       : Scheduled simulation time for this event.
        event_type : Type of event.
        entity     : Associated entity (or None for global events).
        data       : Optional metadata dictionary.
    """
    global _event_counter
    _event_counter += 1
    return Event(
        time=time,
        tie_break=_event_counter,
        event_type=event_type,
        entity=entity,
        data=data or {},
    )


def reset_event_counter() -> None:
    """Reset the global event counter (call before each simulation run)."""
    global _event_counter
    _event_counter = 0
