from __future__ import annotations
import random
from typing import List, Optional
from config import SimConfig
import distributions as dist
from algorithm_sample import AlgorithmSample

_entity_counter = 0  # Global monotonic ID generator

def _next_id() -> int:
    global _entity_counter
    _entity_counter += 1
    return _entity_counter


def reset_entity_counter() -> None:
    """Reset global entity counter (call before each simulation run)."""
    global _entity_counter
    _entity_counter = 0


# Base entity

class Entity:

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
        self.shows_attended:    List[str]     = []

    # ── Satisfaction helpers ──────────────────────────────────────────────────

    def update_satisfaction(self, delta):
        """Update satisfaction and adjust to allowed range [0, 10]."""
        self.satisfaction = max(0, min(10, self.satisfaction + delta))

    # ── Routing ───────────────────────────────────────────────────────────────

    def next_activity(self):
        """Return and consume the next planned activity, or None if done."""
        return self.activity_plan.pop(0) if self.activity_plan else None

    def peek_next_activity(self):
        """Return the next planned activity without consuming it."""
        return self.activity_plan[0] if self.activity_plan else None

    # ── Patience ──────────────────────────────────────────────────────────────

    def get_patience(self) -> float:
        """Maximum wait time (minutes) in queue before abandoning it."""
        raise NotImplementedError
    
    # ── Pricing ───────────────────────────────────────────────────────────────

    def pay_entry(self, has_overnight: bool) -> None:
        """Charge ticket and possibly overnight to spending."""
        if has_overnight:
            self.spending += self.cfg.ticket_with_overnight * self.size
        else:
            self.spending += self.cfg.ticket_price * self.size

    # ── Representation ────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (f"{self.entity_type}(id={self.entity_id}, "
                f"size={self.size}, day={self.day}, "
                f"satisfaction={self.satisfaction:.2f})")

# FriendsGroup

class FriendsGroup(Entity):

    # All station names the group wants to visit after each show
    _ALL_STATIONS = ['PhotoStation', 'ChargingStation', 'MerchTent', 'BodyArt']
    _ALL_SHOWS    = ['MainStage', 'SideStage', 'DJStage']

    def __init__(self, arrival_time: float, cfg: SimConfig):
        size = AlgorithmSample.friends_group_size(cfg.friends_size_min,
                                                  cfg.friends_size_max)
        super().__init__('FriendsGroup', size, arrival_time, 1, cfg)

        self.stays_overnight: bool = (dist.sample_uniform_01() <
                                      cfg.friends_overnight_prob)
        self.remaining_shows: List[str] = list(self._ALL_SHOWS)
        random.shuffle(self.remaining_shows)

        # Build plan for the first show cycle
        self._rebuild_plan()

    def _rebuild_plan(self) -> None:
        """ Actual station ORDER (shortest-queue) is resolved at runtime """
        if self.remaining_shows:
            show = self.remaining_shows.pop(0)
            self.activity_plan = [show, 'AllStations']
        # If no shows remain, entity will depart.

    def on_show_completed(self) -> None:
        """ Schedules the next show cycle after a show attendance ends. """
        # 'AllStations' was already appended; next _rebuild_plan will follow.
        pass

    def on_all_stations_done(self) -> None:
        """Called after the group has visited all stations for one cycle."""
        self._rebuild_plan()

    def get_patience(self) -> float:
        return self.cfg.friends_patience


# Couple

class Couple(Entity):
   
    _SHOWS    = ['MainStage', 'SideStage']
    _STATIONS = ['PhotoStation', 'ChargingStation', 'MerchTent', 'BodyArt']

    def __init__(self, arrival_time: float, day: int, cfg: SimConfig):
        super().__init__('Couple', 2, arrival_time, day, cfg)
        # Couples start with a show
        self.activity_plan.append(random.choice(self._SHOWS))

    def on_show_completed(self) -> None:
        """After a show, schedule one randomly chosen station."""
        self.activity_plan.append(random.choice(self._STATIONS))

    def on_station_completed(self) -> None:
        """After a station, schedule one randomly chosen show."""
        self.activity_plan.append(random.choice(self._SHOWS))

    def should_stay_overnight(self) -> bool:
        """Return True if couple's satisfaction qualifies them for overnight stay."""
        return self.satisfaction > self.cfg.couple_overnight_threshold

    def get_patience(self) -> float:
        return self.cfg.couple_patience


# Single

class Single(Entity):

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


# Factory -  a function to create and return objects for the engine

def create_entity(entity_type: str,
                  arrival_time: float,
                  day: int,
                  cfg: SimConfig) -> Entity:
    
    if entity_type == 'FriendsGroup':
        return FriendsGroup(arrival_time, cfg)
    elif entity_type == 'Couple':
        return Couple(arrival_time, day, cfg)
    elif entity_type == 'Single':
        return Single(arrival_time, day, cfg)
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")
