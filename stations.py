"""
stations.py
===========
Station and stage classes for the Queuechella simulation.

Every physical location in the festival is modelled as one of these classes:

Service Stations  (queue + finite servers):
    EntryGate       – ticket scan + security (2-phase serial service)
    PhotoStation    – photo taking (3 booths, shared FIFO queue)
    ChargingStation – phone charging (150 slots)
    MerchTent       – merchandise purchases (7 cashiers)
    BodyArtStation  – face/body painting (2 artists, mandatory breaks)
    FoodStall       – food ordering + eating (3 separate restaurants)

Concert Stages  (queue + capacity-limited arena):
    MainStage       – mainstream shows, capacity 200, 10-min break
    SideStage       – indie shows, capacity 100, 5-min break
    DJStage         – continuous electronic, capacity 70 concurrent

All stations expose a common interface:
    enqueue(entity)  – add entity to the waiting line
    dequeue()        – remove and return the next entity
    is_busy()        – True if no server is free
    queue_length()   – current length of the waiting line
"""

from __future__ import annotations
from collections import deque
from typing import Deque, List, Optional, Tuple, TYPE_CHECKING

from config import SimConfig
import distributions_delete as dist

if TYPE_CHECKING:
    from entities import Entity


# ─────────────────────────────────────────────────────────────────────────────
# Base service station
# ─────────────────────────────────────────────────────────────────────────────

class ServiceStation:
    """
    Generic multi-server FIFO queue station.

    Attributes:
        name         : Station identifier string.
        num_servers  : Total number of parallel servers.
        busy_servers : Currently occupied server count.
        queue        : FIFO waiting line.
    """

    def __init__(self, name: str, num_servers: int):
        self.name:         str               = name
        self.num_servers:  int               = num_servers
        self.busy_servers: int               = 0
        self.queue:        Deque['Entity']   = deque()

    # ── Queue management ──────────────────────────────────────────────────────

    def enqueue(self, entity: 'Entity') -> None:
        self.queue.append(entity)

    def dequeue(self):
        if len(self.queue) > 0:
            return self.queue.popleft()
        return None

    def queue_length(self) -> int:
        return len(self.queue)

    def is_server_available(self) -> bool:
        return self.busy_servers < self.num_servers

    def acquire_server(self) -> None:
        assert self.busy_servers < self.num_servers, "No server available"
        self.busy_servers += 1

    def release_server(self) -> None:
        assert self.busy_servers > 0, "No server to release"
        self.busy_servers -= 1

    def effective_queue_length(self) -> int:
        """Combined measure: waiting + in service (used for shortest-queue routing)."""
        return self.queue_length() + self.busy_servers

    def __repr__(self) -> str:
        return (f"{self.name}(servers={self.num_servers}, "
                f"busy={self.busy_servers}, queue={self.queue_length()})")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Gate
# ─────────────────────────────────────────────────────────────────────────────

class EntryGate(ServiceStation):
    """
    Festival entry gate with 2-phase serial service:
        Phase 1: Ticket scan   ~ Uniform[1.5, 3.0] minutes
        Phase 2: Security check ~ Exponential(2.0) minutes

    5 parallel clerks; each handles one entity at a time (both phases).
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('EntryGate', cfg.entry_clerks)
        self.cfg = cfg

    def sample_service_time(self) -> float:
        """Total entry service time = scan + security."""
        scan_time     = dist.sample_continuous_uniform(self.cfg.entry_scan_min,
                                                       self.cfg.entry_scan_max)
        security_time = dist.sample_exponential(self.cfg.entry_security_mean)
        return scan_time + security_time


# ─────────────────────────────────────────────────────────────────────────────
# Photo Station
# ─────────────────────────────────────────────────────────────────────────────

class PhotoStation(ServiceStation):
    """
    3 photo booths sharing one FIFO queue.

    Service duration: piecewise linear PDF sampled via Composition method.
    Outcome probabilities:
        0.7 → satisfied: +2 satisfaction, purchase print (30 NIS)
        0.3 → 0.5 chance: −0.5 satisfaction
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('PhotoStation', cfg.photo_stations)
        self.cfg = cfg

    def sample_service_time(self) -> float:
        return dist.sample_photo_duration()

    def process_outcome(self, entity: 'Entity') -> float:
        """
        Apply satisfaction and spending changes after a photo session.
        Returns the satisfaction delta applied.
        """
        if dist.sample_uniform_01() < self.cfg.photo_satisfied_prob:
            entity.update_satisfaction(self.cfg.photo_satisfied_bonus)
            entity.spending += self.cfg.photo_print_cost
            return self.cfg.photo_satisfied_bonus
        else:
            if dist.sample_uniform_01() < self.cfg.photo_unsatisfied_penalty_prob:
                entity.update_satisfaction(-self.cfg.photo_unsatisfied_penalty)
                return -self.cfg.photo_unsatisfied_penalty
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Charging Station
# ─────────────────────────────────────────────────────────────────────────────

class ChargingStation(ServiceStation):
    """
    150 phone charging slots (each slot is a "server").

    Battery level on arrival: Normal(40, 15) clamped to [0, 100).
    Charging duration: custom power-law CDF dependent on battery level.
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('ChargingStation', cfg.charging_slots)
        self.cfg = cfg

    def sample_service_time(self) -> float:
        battery = dist.sample_battery_level(self.cfg.charging_battery_mean,
                                            self.cfg.charging_battery_std)
        return dist.sample_charging_duration(battery)


# ─────────────────────────────────────────────────────────────────────────────
# Merch Tent
# ─────────────────────────────────────────────────────────────────────────────

class MerchTent(ServiceStation):
    """
    7 cashiers for merchandise purchases.

    Service duration: Uniform[2, 6] minutes.
    Each visitor independently buys:
        Festival shirt (p=0.8):  100 NIS
        Festival hat   (p=0.4):   50 NIS
        Flag           (p=0.9):   40 NIS
        Band shirt     (p=0.3):  200 NIS
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('MerchTent', cfg.merch_cashiers)
        self.cfg = cfg

    def sample_service_time(self) -> float:
        return dist.sample_continuous_uniform(self.cfg.merch_service_min,
                                              self.cfg.merch_service_max)

    def process_purchase(self, entity: 'Entity') -> float:
        """
        Simulate merchandise purchases for every REAL PERSON in the entity.
        Returns total revenue from this entity's group.
        """
        total = 0.0
        for _ in range(entity.size):
            if dist.sample_uniform_01() < self.cfg.merch_festival_shirt_prob:
                total += self.cfg.merch_festival_shirt_price
            if dist.sample_uniform_01() < self.cfg.merch_hat_prob:
                total += self.cfg.merch_hat_price
            if dist.sample_uniform_01() < self.cfg.merch_flag_prob:
                total += self.cfg.merch_flag_price
            if dist.sample_uniform_01() < self.cfg.merch_band_shirt_prob:
                total += self.cfg.merch_band_shirt_price
        entity.spending += total
        return total


# ─────────────────────────────────────────────────────────────────────────────
# Body Art Station
# ─────────────────────────────────────────────────────────────────────────────

class BodyArtStation(ServiceStation):
    """
    2 body art artists.

    Art types (chosen randomly for each person in the entity):
        Glitter & gems (p=0.3): Normal(15, 3) min;
            p=0.7 satisfied → +0.8 satisfaction
        Neon paint     (p=0.3): Exponential(12) min;
            p=0.6 satisfied → +1.2 satisfaction
        Henna tattoo   (p=0.4): Uniform[17,22] min;
            p=0.8 satisfied → +0.7 satisfaction

    Artists take a mandatory 15-minute break after every 10 drawings.
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('BodyArt', cfg.body_art_artists)
        self.cfg = cfg
        # Per-artist drawing counter and break flag
        self.artist_drawing_counts: List[int]  = [0] * cfg.body_art_artists
        self.artist_on_break:       List[bool] = [False] * cfg.body_art_artists

    def get_available_artist(self) -> Optional[int]:
        """Return index of first available (free, not on break) artist."""
        for i in range(len(self.artist_drawing_counts)):
            if not self.artist_on_break[i]:
                return i
        return None

    def is_server_available(self) -> bool:
        """
        Override: an artist counts as available only if they are NOT on break.
        Without this, the engine could assign a new entity to a station even
        when all artists are on their mandatory break.
        """
        free_artists = sum(1 for on_break in self.artist_on_break
                           if not on_break)
        return self.busy_servers < free_artists

    def sample_service_time(self, artist_idx: int) -> Tuple[float, str]:
        """
        Sample service duration for one entity visit.
        The entity represents 1 slot regardless of group size
        (each person in the group queues separately for body art –
        but since entities move as a group, we approximate with the
        max service time across group members for simplicity).

        Returns (duration, art_type) so the caller can later use the
        SAME art_type for the satisfaction outcome — sampling it twice
        would let an entity get henna's duration but glitter's bonus.
        """
        art_type = dist.sample_art_type()
        return dist.sample_body_art_duration(art_type), art_type

    def record_drawing_complete(self, artist_idx: int) -> bool:
        """
        Increment drawing count for artist.
        Returns True if artist must now take a break.
        """
        self.artist_drawing_counts[artist_idx] += 1
        if self.artist_drawing_counts[artist_idx] % self.cfg.body_art_break_after == 0:
            self.artist_on_break[artist_idx] = True
            return True
        return False

    def artist_break_done(self, artist_idx: int) -> None:
        """Called when an artist's mandatory break ends."""
        self.artist_on_break[artist_idx] = False

    def process_outcome(self, entity: 'Entity', art_type: str) -> float:
        """
        Apply satisfaction changes for body art experience.
        Uses the SAME art_type that was sampled for the service time so
        duration and outcome refer to the same drawing.
        Returns satisfaction delta.
        """
        cfg = self.cfg

        if art_type == 'glitter':
            if dist.sample_uniform_01() < cfg.glitter_satisfied_prob:
                entity.update_satisfaction(cfg.glitter_satisfied_bonus)
                return cfg.glitter_satisfied_bonus
        elif art_type == 'neon':
            if dist.sample_uniform_01() < cfg.neon_satisfied_prob:
                entity.update_satisfaction(cfg.neon_satisfied_bonus)
                return cfg.neon_satisfied_bonus
        elif art_type == 'henna':
            if dist.sample_uniform_01() < cfg.henna_satisfied_prob:
                entity.update_satisfaction(cfg.henna_satisfied_bonus)
                return cfg.henna_satisfied_bonus
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Food Stall (one restaurant)
# ─────────────────────────────────────────────────────────────────────────────

class FoodStall(ServiceStation):
    """
    One food restaurant with a single cashier queue.

    Service time (ordering + payment): Normal(5, 1.5) minutes.
    Preparation time: depends on restaurant type.
    Eating time: Uniform[15, 35] minutes.
    Dissatisfied (p=0.4): −0.6 satisfaction.
    """

    def __init__(self, restaurant_type: str, cfg: SimConfig):
        super().__init__(f'FoodStall_{restaurant_type}', num_servers=1)
        self.restaurant_type = restaurant_type
        self.cfg = cfg

    def sample_order_service_time(self) -> float:
        return dist.sample_food_service_time(self.cfg.food_service_mean,
                                             self.cfg.food_service_std)

    def sample_prep_time(self) -> float:
        rt = self.restaurant_type
        if rt == 'pizza':
            return dist.sample_continuous_uniform(self.cfg.pizza_prep_min,
                                                  self.cfg.pizza_prep_max)
        elif rt == 'burger':
            return dist.sample_continuous_uniform(self.cfg.burger_prep_min,
                                                  self.cfg.burger_prep_max)
        elif rt == 'asian':
            return dist.sample_continuous_uniform(self.cfg.asian_prep_min,
                                                  self.cfg.asian_prep_max)
        else:
            raise ValueError(f"Unknown restaurant type: {rt}")

    def sample_eating_time(self) -> float:
        return dist.sample_continuous_uniform(self.cfg.food_eating_min,
                                              self.cfg.food_eating_max)

    def calculate_meal_cost(self, entity: 'Entity') -> float:
        """Calculate food cost for the entire entity group."""
        rt = self.restaurant_type
        if rt == 'pizza':
            # Individuals: personal serving; groups: may share family platters
            people = entity.size
            if entity.entity_type == 'Single':
                return self.cfg.pizza_individual_price
            else:
                serves = self.cfg.pizza_family_serves
                family_platters = people // serves
                leftover        = people %  serves
                return (family_platters * self.cfg.pizza_family_price +
                        leftover * self.cfg.pizza_individual_price)
        elif rt == 'burger':
            return self.cfg.burger_price * entity.size
        elif rt == 'asian':
            return self.cfg.asian_price * entity.size
        return 0.0

    def process_outcome(self, entity: 'Entity') -> float:
        """Apply satisfaction penalty if food is unsatisfactory."""
        if dist.sample_uniform_01() < self.cfg.food_unsatisfied_prob:
            entity.update_satisfaction(-self.cfg.food_unsatisfied_penalty)
            return -self.cfg.food_unsatisfied_penalty
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Concert Stage  (capacity-limited arena)
# ─────────────────────────────────────────────────────────────────────────────

class Stage:
    """
    Concert stage with sequential performances and a capacity-limited arena.

    Attributes:
        name            : Stage identifier.
        capacity        : Maximum simultaneous guests (in real people).
        current_guests  : Real people currently inside the arena.
        audience        : List of (entity, entry_order) in current show.
        queue           : FIFO line of entities waiting for the next show.
        show_in_progress: Whether a show is currently running.
        show_end_time   : Simulation clock time when current show ends.
        show_count      : Total number of completed shows.
        genre           : Music genre label ('mainstream', 'indie', 'electronic').
        genre_weight    : G value for satisfaction formula.
    """

    def __init__(self, name: str, capacity: int, genre: str, genre_weight: int):
        self.name:             str            = name
        self.capacity:         int            = capacity
        self.genre:            str            = genre
        self.genre_weight:     int            = genre_weight

        self.current_guests:   int            = 0
        self.audience:         List[Tuple['Entity', int]] = []  # (entity, entry_order)
        self.queue:            Deque['Entity']= deque()
        self.show_in_progress: bool           = False
        self.show_end_time:    float          = 0.0
        self.show_count:       int            = 0
        self.entry_order_counter: int         = 0   # for position tracking

    def available_capacity(self) -> int:
        """Real people that can still enter the arena."""
        return self.capacity - self.current_guests

    def queue_length(self) -> int:
        return len(self.queue)

    def effective_queue_length(self) -> int:
        """Used for shortest-queue routing decisions."""
        return len(self.queue)

    def enqueue(self, entity: 'Entity') -> None:
        self.queue.append(entity)

    def admit_from_queue(self) -> List['Entity']:
        """
        Fill available arena spots from the queue using the MaxFill policy:
        Go through the queue in order; admit an entity if it fits (size <=
        available capacity).  Skip if it doesn't fit, check smaller entities.
        Returns list of admitted entities.

        Reference: "המדיניות היא שבכל הופעה יש להכניס את הכמות המקסימלית"
        """
        admitted = []
        remaining_queue = list(self.queue)
        self.queue.clear()

        while remaining_queue:
            avail = self.available_capacity()
            if avail <= 0:
                break

            # Find first entity that fits
            admitted_one = False
            for i, entity in enumerate(remaining_queue):
                if entity.size <= avail:
                    self._enter_arena(entity)
                    admitted.append(entity)
                    remaining_queue.pop(i)
                    admitted_one = True
                    break

            if not admitted_one:
                break  # Smallest remaining entity still doesn't fit

        # Put unselected entities back in queue (preserve relative order)
        self.queue.extend(remaining_queue)
        return admitted

    def _enter_arena(self, entity: 'Entity') -> None:
        """Record entity entering the arena."""
        self.entry_order_counter += 1
        self.current_guests += entity.size
        self.audience.append((entity, self.entry_order_counter))

    def remove_from_audience(self, entity: 'Entity') -> None:
        """Remove entity from arena (early leave or show end)."""
        self.audience = [(e, o) for e, o in self.audience if e is not entity]
        self.current_guests -= entity.size

    def get_back_row_entities(self) -> List['Entity']:
        """
        Return the 10 entities with the highest entry-order numbers
        (i.e., the entities that entered last → furthest from stage).
        Only relevant for MainStage early-leave logic.
        """
        if not self.audience:
            return []
        sorted_audience = sorted(self.audience, key=lambda x: x[1], reverse=True)
        return [e for e, _ in sorted_audience[:10]]

    def start_show(self, show_end_time: float) -> List['Entity']:
        """
        Begin a new performance.  Clears audience, fills from queue, marks
        show as in-progress.
        Returns the list of entities that just entered.
        """
        self.show_in_progress = True
        self.show_end_time    = show_end_time
        self.show_count      += 1
        self.entry_order_counter = 0
        self.current_guests  = 0
        self.audience        = []

        return self.admit_from_queue()

    def end_show(self) -> List['Entity']:
        """
        End the current performance.  Returns all entities that were inside.
        """
        self.show_in_progress = False
        departed = [e for e, _ in self.audience]
        self.audience        = []
        self.current_guests  = 0
        return departed

    def compute_satisfaction_delta(self, show_end_time: float) -> float:
        """
        Compute satisfaction change for a show experience.

        With probability 0.5: positive experience
            score = (G - 1) / 2  +  (T - 1) / 19
            where G = genre weight (3=mainstream, 2=indie, 1=electronic)
                  T = hour (integer) when show ended
        With probability 0.5: negative experience → -1.0

        Reference: specification page 6.
        """
        if dist.sample_uniform_01() < 0.5:
            # Positive experience
            # show_end_time is in minutes from midnight of day 1, so a day-2
            # show ending at 19:00 would give T = 30 with int(t/60). We need
            # the *hour of day* (1-24), so wrap via modulo 24.
            T = int(show_end_time / 60) % 24
            G = self.genre_weight
            return (G - 1) / 2.0 + (T - 1) / 19.0
        else:
            return -1.0

    def __repr__(self) -> str:
        return (f"{self.name}(capacity={self.capacity}, "
                f"guests={self.current_guests}, queue={self.queue_length()}, "
                f"show={'ON' if self.show_in_progress else 'OFF'})")


# ─────────────────────────────────────────────────────────────────────────────
# Specialised stages
# ─────────────────────────────────────────────────────────────────────────────

class MainStage(Stage):
    """
    Mainstream concerts (capacity 200, 10-min break between shows).

    Durations come from the Excel sample data (distribution fitted separately).
    Default fallback: Exponential(60) minutes (placeholder until data fitted).

    Special rule: last 10 entities (back rows) may leave 15 min into the show
    with probability 0.5.
    """

    def __init__(self, cfg: SimConfig, duration_sampler=None):
        super().__init__('MainStage', cfg.main_stage_capacity,
                         genre='mainstream', genre_weight=cfg.main_stage_genre_weight)
        self.break_duration   = cfg.main_stage_break
        self.early_leave_prob = cfg.main_stage_early_leave_prob
        self.early_leave_delay = cfg.main_stage_early_leave_delay

        # Duration sampler: callable → float (minutes)
        # Should be replaced after distribution fitting.
        self._duration_sampler = duration_sampler or self._default_duration

    def _default_duration(self) -> float:
        """Placeholder until Excel data is fitted. Exponential mean=60 min."""
        return dist.sample_exponential(60.0)

    def sample_show_duration(self) -> float:
        return self._duration_sampler()

    def set_duration_sampler(self, sampler) -> None:
        """Inject a fitted duration sampler from distribution_fitting module."""
        self._duration_sampler = sampler


class SideStage(Stage):
    """
    Indie concerts (capacity 100, 5-min break, Uniform[20,30] duration).
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('SideStage', cfg.side_stage_capacity,
                         genre='indie', genre_weight=2)
        self.break_duration = cfg.side_stage_break
        self._dur_min       = cfg.side_stage_duration_min
        self._dur_max       = cfg.side_stage_duration_max

    def sample_show_duration(self) -> float:
        return dist.sample_continuous_uniform(self._dur_min, self._dur_max)


class DJStage(Stage):
    """
    Electronic / DJ stage: music plays continuously all day.
    Capacity: 70 concurrent guests at any moment.

    Instead of shows, each entity independently stays for a sampled duration
    (Accept-Reject sampler) and then leaves.  New entities can enter whenever
    capacity allows.
    """

    def __init__(self, cfg: SimConfig):
        super().__init__('DJStage', cfg.dj_stage_capacity,
                         genre='electronic', genre_weight=1)
        # Override show mechanics – DJStage is always "in progress"
        self.show_in_progress = True

    def enter(self, entity: 'Entity') -> bool:
        """
        Attempt to admit entity.  Returns True if admitted (space available).
        """
        if entity.size <= self.available_capacity():
            self._enter_arena(entity)
            return True
        return False

    def exit(self, entity: 'Entity') -> None:
        """Entity leaves the DJ stage."""
        self.remove_from_audience(entity)

    def sample_stay_duration(self) -> float:
        """DJ stage stay duration via Accept-Reject sampler."""
        return dist.sample_dj_duration()


# ─────────────────────────────────────────────────────────────────────────────
# Festival: container for all stations
# ─────────────────────────────────────────────────────────────────────────────

class Festival:
    """
    Aggregates all stations and stages for one simulation run.

    Provides a single lookup interface and the shortest-queue helper used
    by FriendsGroup routing.
    """

    STATION_NAMES = ['PhotoStation', 'ChargingStation', 'MerchTent', 'BodyArt']
    STAGE_NAMES   = ['MainStage', 'SideStage', 'DJStage']

    def __init__(self, cfg: SimConfig):
        self.cfg = cfg

        # Service stations
        self.entry_gate       = EntryGate(cfg)
        self.photo_station    = PhotoStation(cfg)
        self.charging_station = ChargingStation(cfg)
        self.merch_tent       = MerchTent(cfg)
        self.body_art         = BodyArtStation(cfg)

        # Food stalls (one queue per restaurant)
        self.food_burger = FoodStall('burger', cfg)
        self.food_pizza  = FoodStall('pizza',  cfg)
        self.food_asian  = FoodStall('asian',  cfg)

        # Stages
        self.main_stage = MainStage(cfg)
        self.side_stage = SideStage(cfg)
        self.dj_stage   = DJStage(cfg)

        # Convenient name → object map
        self.stations: dict = {
            'EntryGate':       self.entry_gate,
            'PhotoStation':    self.photo_station,
            'ChargingStation': self.charging_station,
            'MerchTent':       self.merch_tent,
            'BodyArt':         self.body_art,
            'FoodStall_burger': self.food_burger,
            'FoodStall_pizza':  self.food_pizza,
            'FoodStall_asian':  self.food_asian,
        }
        self.stages: dict = {
            'MainStage': self.main_stage,
            'SideStage': self.side_stage,
            'DJStage':   self.dj_stage,
        }

    def get_station(self, name: str):
        return self.stations.get(name) or self.stages.get(name)

    def shortest_queue_station(self,
                               exclude: Optional[List[str]] = None) -> str:
        """
        Return the name of the service station with the shortest effective
        queue (queue length + busy servers).

        Args:
            exclude: Station names to skip (e.g., stages, food stalls).
        """
        exclude = exclude or []
        candidates = {
            name: self.stations[name].effective_queue_length()
            for name in self.STATION_NAMES
            if name not in exclude and name in self.stations
        }
        return min(candidates, key=candidates.get)

    def ordered_stations_by_queue(self,
                                  exclude: Optional[List[str]] = None
                                  ) -> List[str]:
        """
        Return all service station names sorted by current queue length
        (shortest first).
        """
        exclude = exclude or []
        candidates = [
            (name, self.stations[name].effective_queue_length())
            for name in self.STATION_NAMES
            if name not in exclude and name in self.stations
        ]
        return [name for name, _ in sorted(candidates, key=lambda x: x[1])]

    def set_main_stage_sampler(self, sampler) -> None:
        """Inject a fitted duration sampler into MainStage."""
        self.main_stage.set_duration_sampler(sampler)
