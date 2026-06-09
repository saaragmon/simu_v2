"""
config.py
=========
Central configuration for the Queuechella festival simulation.
All magic numbers live here so that alternatives can override them cleanly.

Usage:
    from config import SimConfig
    cfg = SimConfig()           # baseline
    cfg = SimConfig(photo_stations=4)   # override single param
"""

from dataclasses import dataclass, field
from typing import Optional


# ─── Time constants (all times in MINUTES from midnight) ───────────────────────
FESTIVAL_START: int = 9 * 60        # 09:00
FESTIVAL_END:   int = 20 * 60       # 20:00
DAY_DURATION:   int = FESTIVAL_END - FESTIVAL_START   # 660 min
NUM_DAYS:       int = 2


@dataclass
class SimConfig:
    """
    Simulation configuration.
    Baseline values reflect the current (as-is) festival state.
    Override any field to model an alternative scenario.
    """

    # ── Satisfaction score ─────────────────────────────────────────────────────
    initial_satisfaction: float = 5.0
    max_satisfaction:     float = 10.0
    min_satisfaction:     float = 0.0

    # ── Entry Gate ─────────────────────────────────────────────────────────────
    entry_clerks:           int   = 5
    entry_scan_min:         float = 1.5    # minutes, continuous uniform
    entry_scan_max:         float = 3.0
    entry_security_mean:    float = 2.0    # minutes, exponential

    # ── FriendsGroup ──────────────────────────────────────────────────────────
    friends_size_min:       int   = 3
    friends_size_max:       int   = 6
    friends_arrival_start:  int   = 9 * 60   # 09:00, day 1 only
    friends_arrival_end:    int   = 13 * 60  # 13:00
    friends_overnight_prob: float = 0.7
    friends_patience:       float = 15.0     # minutes before queue abandon
    friends_abandon_penalty:float = 2.0      # satisfaction drop on abandon

    # ── Couple ────────────────────────────────────────────────────────────────
    couple_arrival_rate:    float = 60.0     # per HOUR (exponential)
    couple_arrival_start:   int   = 10 * 60  # 10:00
    couple_arrival_end:     int   = 16 * 60  # 16:00
    couple_overnight_threshold: float = 7.0  # satisfaction must exceed this
    couple_patience:        float = 20.0
    couple_abandon_penalty: float = 1.5

    # ── Single ────────────────────────────────────────────────────────────────
    single_arrival_rate_per_day: float = 500.0   # exponential rate / day
    single_arrival_start:   int   = 9 * 60
    single_arrival_end:     int   = 16 * 60
    single_patience:        float = 20.0
    single_abandon_penalty: float = 1.0

    # ── Arrival rate scale factor (for "marketing" alternative) ───────────────
    arrival_rate_multiplier: float = 1.0   # 1.2 = +20% arrivals

    # ── MainStage ─────────────────────────────────────────────────────────────
    main_stage_capacity:    int   = 200
    main_stage_break:       float = 10.0   # minutes between shows
    main_stage_early_leave_prob: float = 0.5
    main_stage_early_leave_delay: float = 15.0  # minutes after entry
    main_stage_genre_weight: int  = 3      # G value in satisfaction formula

    # ── SideStage ─────────────────────────────────────────────────────────────
    side_stage_capacity:    int   = 100
    side_stage_break:       float = 5.0
    side_stage_duration_min: float = 20.0
    side_stage_duration_max: float = 30.0

    # ── DJStage ───────────────────────────────────────────────────────────────
    dj_stage_capacity:      int   = 70     # concurrent guests at any moment

    # ── PhotoStation ──────────────────────────────────────────────────────────
    photo_stations:         int   = 3
    photo_satisfied_prob:   float = 0.7
    photo_satisfied_bonus:  float = 2.0
    photo_unsatisfied_penalty_prob: float = 0.5
    photo_unsatisfied_penalty:      float = 0.5
    photo_print_cost:       float = 30.0   # NIS

    # ── ChargingStation ───────────────────────────────────────────────────────
    charging_slots:         int   = 150
    charging_battery_mean:  float = 40.0
    charging_battery_std:   float = 15.0

    # ── MerchTent ─────────────────────────────────────────────────────────────
    merch_cashiers:         int   = 7
    merch_service_min:      float = 2.0
    merch_service_max:      float = 6.0
    merch_festival_shirt_prob:  float = 0.8
    merch_festival_shirt_price: float = 100.0
    merch_hat_prob:         float = 0.4
    merch_hat_price:        float = 50.0
    merch_flag_prob:        float = 0.9
    merch_flag_price:       float = 40.0
    merch_band_shirt_prob:  float = 0.3
    merch_band_shirt_price: float = 200.0

    # ── BodyArt ───────────────────────────────────────────────────────────────
    body_art_artists:       int   = 2
    body_art_break_after:   int   = 10     # drawings before mandatory break
    body_art_break_duration: float = 15.0
    glitter_prob:           float = 0.3
    glitter_satisfied_prob: float = 0.7
    glitter_satisfied_bonus: float = 0.8
    glitter_duration_mean:  float = 15.0
    glitter_duration_std:   float = 3.0
    neon_prob:              float = 0.3
    neon_satisfied_prob:    float = 0.6
    neon_satisfied_bonus:   float = 1.2
    neon_duration_mean:     float = 12.0
    henna_prob:             float = 0.4
    henna_satisfied_prob:   float = 0.8
    henna_satisfied_bonus:  float = 0.7
    henna_duration_min:     float = 17.0
    henna_duration_max:     float = 22.0

    # ── Food Stalls ───────────────────────────────────────────────────────────
    food_lunch_start:       int   = 13 * 60
    food_lunch_end:         int   = 15 * 60
    food_lunch_prob:        float = 0.70
    food_service_mean:      float = 5.0
    food_service_std:       float = 1.5
    food_eating_min:        float = 15.0
    food_eating_max:        float = 35.0
    food_unsatisfied_prob:  float = 0.4
    food_unsatisfied_penalty: float = 0.6
    burger_prob:            float = 3 / 8
    pizza_prob:             float = 1 / 4
    # asian_prob = 1 - burger_prob - pizza_prob  (derived)
    pizza_prep_min:         float = 4.0
    pizza_prep_max:         float = 6.0
    pizza_individual_price: float = 40.0
    pizza_family_price:     float = 100.0
    burger_prep_min:        float = 3.0
    burger_prep_max:        float = 4.0
    burger_price:           float = 100.0
    asian_prep_min:         float = 3.0
    asian_prep_max:         float = 7.0
    asian_price:            float = 65.0
    pizza_family_serves:    int   = 3       # one family platter feeds this many people

    # ── Ticket pricing ────────────────────────────────────────────────────────
    ticket_price:           float = 500.0
    overnight_price:        float = 250.0
    ticket_with_overnight:  float = 700.0

    # ── Visitor gift (alternative) ────────────────────────────────────────────
    visitor_gift_initial_satisfaction: float = 5.0  # raised to 6.5 in alternative

    # ── Statistical analysis ──────────────────────────────────────────────────
    confidence_level:       float = 0.95
    relative_precision:     float = 0.1

    @property
    def asian_prob(self) -> float:
        return 1.0 - self.burger_prob - self.pizza_prob

    @property
    def couple_arrival_rate_per_min(self) -> float:
        """Convert from per-hour rate to per-minute rate."""
        return self.couple_arrival_rate / 60.0

    @property
    def single_arrival_rate_per_min(self) -> float:
        """
        Convert the per-day Singles arrival rate to per-minute.

        Per the project spec, Singles arrive only during a 7-hour window
        (09:00-16:00 = 420 min), not over the full 11-hour festival day.
        So `500 / day` means 500 expected arrivals spread over those 7
        hours, giving a per-minute rate of 500 / 420.
        """
        single_arrival_window_min = (
            self.single_arrival_end - self.single_arrival_start)
        return self.single_arrival_rate_per_day / single_arrival_window_min


# ─── Pre-built alternative configs ────────────────────────────────────────────

def baseline_config() -> SimConfig:
    """Return the as-is festival configuration."""
    return SimConfig()


def alt_better_kitchen(base: Optional[SimConfig] = None) -> SimConfig:
    """Better kitchen staff – 500,000 NIS."""
    cfg = base or SimConfig()
    cfg.food_unsatisfied_prob = 0.10
    cfg.food_lunch_prob       = 0.85
    return cfg


def alt_expanded_security(base: Optional[SimConfig] = None) -> SimConfig:
    """Expanded security team – 650,000 NIS (+30% stage capacity)."""
    cfg = base or SimConfig()
    cfg.main_stage_capacity = int(200 * 1.30)
    cfg.side_stage_capacity = int(100 * 1.30)
    cfg.dj_stage_capacity   = int(70  * 1.30)
    return cfg


def alt_popular_bands(base: Optional[SimConfig] = None) -> SimConfig:
    """Popular mainstream bands – 300,000 NIS."""
    cfg = base or SimConfig()
    cfg.merch_band_shirt_prob   = 0.80
    cfg.main_stage_genre_weight = 4   # G = 4 in satisfaction formula
    return cfg


def alt_extra_photo_and_body_art(base: Optional[SimConfig] = None) -> SimConfig:
    """Extra photo station + body art artist – 150,000 NIS."""
    cfg = base or SimConfig()
    cfg.photo_stations   = 4
    cfg.body_art_artists = 3
    return cfg


def alt_marketing(base: Optional[SimConfig] = None) -> SimConfig:
    """Festival marketing – 200,000 NIS (+20% arrival rate)."""
    cfg = base or SimConfig()
    cfg.arrival_rate_multiplier = 1.20
    return cfg


def alt_auto_ticket_scan(base: Optional[SimConfig] = None) -> SimConfig:
    """Automatic ticket scanning – 600,000 NIS (no scan time, only security)."""
    cfg = base or SimConfig()
    cfg.entry_scan_min = 0.0
    cfg.entry_scan_max = 0.0
    return cfg


def alt_visitor_gift(base: Optional[SimConfig] = None) -> SimConfig:
    """Visitor gift bag – 200,000 NIS (satisfaction starts at 6.5)."""
    cfg = base or SimConfig()
    cfg.visitor_gift_initial_satisfaction = 6.5
    cfg.initial_satisfaction = 6.5
    return cfg
