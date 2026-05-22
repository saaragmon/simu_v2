"""
entities.py
===========
Visitor entity classes for the Queuechella simulation.

Each entity type encapsulates its own routing plan, patience, and satisfaction
update logic.  Entities always move as a UNIT (all members wait together),
so the `size` attribute determines how many physical spots are occupied
inside a stage or station.

Class hierarchy:
    Entity (abstract base)
    ├── FriendsGroup
    ├── Couple
    └── Single
"""

from __future__ import annotations
import random
from typing import List, Optional
from simulation.config import SimConfig
from simulation import distributions as dist


_entity_counter = 0  # Global monotonic ID generator


def _next_id() -> int:
    global _entity_counter
    _entity_counter += 1
    return _entity_counter


def reset_entity_counter() -> None:
    """Reset global entity counter (call before each simulation run)."""
    global _entity_counter
    _entity_counter = 0


# ─────────────────────────────────────────────────────────────────────────────
# Base entity
# ─────────────────────────────────────────────────────────────────────────────

class Entity:
    """
    Abstract base class for all festival visitor entities.

    Attributes:
        entity_id     : Unique simulation identifier.
        entity_type   : Human-readable class label.
        size          : Number of real people this entity represents.
        arrival_time  : Simulation-clock minute when entity arrives at gate.
        day           : Which festival day (1 or 2) the entity arrives.
        satisfaction  : Current satisfaction score [0, 10].
        spending      : Total NIS spent during the visit.
        activity_plan : Ordered list of remaining activities to perform.
        departed      : Whether the entity has left the festival.
        queue_join_time: Clock minute when this entity joined the current queue.
    """

    def __init__(self,
                 entity_type: str,
                 size: int,
                 arrival_time: float,
                 day: int,
                 cfg: SimConfig):
        self.entity_id:    int   = _next_id()
        self.entity_type:  str   = entity_type
        self.size:         int   = size
        self.arrival_time: float = arrival_time
        self.day:          int   = day
        self.cfg:          SimConfig = cfg

        self.satisfaction:      float         = cfg.initial_satisfaction
        self.spending:          float         = 0.0
        self.activity_plan:     List[str]     = []
        self.departed:          bool          = False
        self.queue_join_time:   Optional[float] = None

        # Track which shows have been attended (for FriendsGroup logic)
        self.shows_attended:    List[str]     = []

    # ── Satisfaction helpers ──────────────────────────────────────────────────

    def update_satisfaction(self, delta: float) -> None:
        """Clamp satisfaction to [min, max] after applying delta."""
        self.satisfaction = max(
            self.cfg.min_satisfaction,
            min(self.cfg.max_satisfaction, self.satisfaction + delta)
        )

    # ── Routing ───────────────────────────────────────────────────────────────

    def next_activity(self) -> Optional[str]:
        """Return and consume the next planned activity, or None if done."""
        if self.activity_plan:
            return self.activity_plan.pop(0)
        return None

    def peek_next_activity(self) -> Optional[str]:
        """Return the next planned activity without consuming it."""
        return self.activity_plan[0] if self.activity_plan else None

    # ── Patience ──────────────────────────────────────────────────────────────

    def get_patience(self) -> float:
        """Maximum queue wait time (minutes) before abandonment."""
        raise NotImplementedError

    # ── Pricing ───────────────────────────────────────────────────────────────

    def pay_entry(self, has_overnight: bool) -> None:
        """Charge ticket (and optional overnight) to spending."""
        if has_overnight:
            self.spending += self.cfg.ticket_with_overnight * self.size
        else:
            self.spending += self.cfg.ticket_price * self.size

    # ── Representation ────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (f"{self.entity_type}(id={self.entity_id}, "
                f"size={self.size}, day={self.day}, "
                f"satisfaction={self.satisfaction:.2f})")


# ─────────────────────────────────────────────────────────────────────────────
# FriendsGroup
# ─────────────────────────────────────────────────────────────────────────────

class FriendsGroup(Entity):
    """
    A group of 3-6 friends arriving together on Day 1 (09:00-13:00).

    Routing plan:
        For each show type {MainStage, SideStage, DJStage}:
            - Watch the full show.
            - Visit ALL stations in shortest-queue order (decided at runtime).
        After completing all 3 rounds: entity departs.

    Overnight logic:
        With probability 0.7 the group stays overnight (decided at creation).
        If they stay, they re-enter the activity cycle on Day 2.
    """

    # All station names the group wants to visit after each show
    _ALL_STATIONS = ['PhotoStation', 'ChargingStation', 'MerchTent', 'BodyArt']
    _ALL_SHOWS    = ['MainStage', 'SideStage', 'DJStage']

    def __init__(self, arrival_time: float, cfg: SimConfig):
        size = dist.sample_discrete_uniform(cfg.friends_size_min,
                                            cfg.friends_size_max)
        super().__init__('FriendsGroup', size, arrival_time, 1, cfg)

        self.stays_overnight: bool = (dist.sample_uniform_01() <
                                      cfg.friends_overnight_prob)
        self.remaining_shows: List[str] = list(self._ALL_SHOWS)
        random.shuffle(self.remaining_shows)

        # Build plan for the first show cycle
        self._rebuild_plan()

    def _rebuild_plan(self) -> None:
        """
        Build the activity plan for one show cycle.
        The actual station ORDER (shortest-queue) is resolved at runtime by
        the engine; here we just insert a SENTINEL 'AllStations' token that
        the engine expands.
        """
        if self.remaining_shows:
            show = self.remaining_shows.pop(0)
            self.activity_plan = [show, 'AllStations']
        # If no shows remain, activity_plan stays empty → entity will depart.

    def on_show_completed(self) -> None:
        """
        Called by the engine after a show attendance ends.
        Schedules the next show cycle if shows remain.
        """
        # 'AllStations' was already appended; next _rebuild_plan will follow.
        pass

    def on_all_stations_done(self) -> None:
        """Called after the group has visited all stations for one cycle."""
        self._rebuild_plan()

    def get_patience(self) -> float:
        return self.cfg.friends_patience


# ─────────────────────────────────────────────────────────────────────────────
# Couple
# ─────────────────────────────────────────────────────────────────────────────

class Couple(Entity):
    """
    A couple (2 people) that alternates between shows and stations.

    Routing plan (dynamic):
        - Dislikes electronic music → never visits DJStage.
        - After a show → randomly pick one station (equal probability).
        - After a station → randomly pick one show (MainStage or SideStage,
          equal probability).
        - Continues until the festival day ends.

    Overnight logic:
        Stays overnight only if satisfaction > 7.0 at the end of Day 1.
    """

    _SHOWS    = ['MainStage', 'SideStage']
    _STATIONS = ['PhotoStation', 'ChargingStation', 'MerchTent', 'BodyArt']

    def __init__(self, arrival_time: float, day: int, cfg: SimConfig):
        super().__init__('Couple', 2, arrival_time, day, cfg)
        # Couples start with a show
        self._schedule_next_show()

    def _schedule_next_show(self) -> None:
        """Append a randomly chosen show to the plan."""
        show = random.choice(self._SHOWS)
        self.activity_plan.append(show)

    def _schedule_next_station(self) -> None:
        """Append a randomly chosen station to the plan."""
        station = random.choice(self._STATIONS)
        self.activity_plan.append(station)

    def on_show_completed(self) -> None:
        """After a show, schedule one station."""
        self._schedule_next_station()

    def on_station_completed(self) -> None:
        """After a station, schedule one show."""
        self._schedule_next_show()

    def should_stay_overnight(self) -> bool:
        """Return True if couple's satisfaction qualifies them for overnight stay."""
        return self.satisfaction > self.cfg.couple_overnight_threshold

    def get_patience(self) -> float:
        return self.cfg.couple_patience


# ─────────────────────────────────────────────────────────────────────────────
# Single
# ─────────────────────────────────────────────────────────────────────────────

class Single(Entity):
    """
    A solo visitor with a fixed activity plan.

    Routing plan (fixed):
        1. MerchTent (always first)
        2. 2 × MainStage shows  (shortest-queue preference)
        3. 2 × SideStage shows  (shortest-queue preference)
        4. 1 × DJStage show

    Arrival: Either Day 1 or Day 2 (equal probability); stays one day only.
    """

    def __init__(self, arrival_time: float, day: int, cfg: SimConfig):
        super().__init__('Single', 1, arrival_time, day, cfg)
        self.activity_plan = [
            'MerchTent',
            'MainStage', 'MainStage',
            'SideStage', 'SideStage',
            'DJStage',
        ]

    def get_patience(self) -> float:
        return self.cfg.single_patience


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_entity(entity_type: str,
                  arrival_time: float,
                  day: int,
                  cfg: SimConfig) -> Entity:
    """
    Factory function to create an entity by type string.

    Args:
        entity_type  : 'FriendsGroup' | 'Couple' | 'Single'
        arrival_time : Simulation clock value (minutes).
        day          : Festival day (1 or 2).
        cfg          : Simulation configuration.
    """
    if entity_type == 'FriendsGroup':
        return FriendsGroup(arrival_time, cfg)
    elif entity_type == 'Couple':
        return Couple(arrival_time, day, cfg)
    elif entity_type == 'Single':
        return Single(arrival_time, day, cfg)
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")
