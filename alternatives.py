"""
alternatives.py
===============
Alternative scenario definitions and comparison runner.

Budget constraint: 1,000,000 NIS total per combination.

Available alternatives (from project spec):
    1. Better Kitchen Staff       – 500,000 NIS
    2. Expanded Security Team     – 650,000 NIS  (+30% stage capacity)
    3. Popular Mainstream Bands   – 300,000 NIS
    4. Extra Photo + Body Art     – 150,000 NIS
    5. Marketing Campaign         – 200,000 NIS  (+20% arrivals)
    6. Automatic Ticket Scanning  – 600,000 NIS  (no scan time)
    7. Visitor Gift Bag           – 200,000 NIS  (satisfaction starts at 6.5)

Two example budget-feasible combinations (choose at least 2 in the project):
    Combo A: alt 4 + alt 3 + alt 7   = 150k + 300k + 200k = 650k  (within budget)
    Combo B: alt 1 + alt 5            = 500k + 200k = 700k  (within budget)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List

from simulation.config import SimConfig
from simulation.config import (
    baseline_config,
    alt_better_kitchen,
    alt_expanded_security,
    alt_popular_bands,
    alt_extra_photo_and_body_art,
    alt_marketing,
    alt_auto_ticket_scan,
    alt_visitor_gift,
)


BUDGET_LIMIT = 1_000_000  # NIS


@dataclass
class Alternative:
    """Describes a single alternative scenario."""
    name:        str
    cost:        int          # NIS
    description: str
    config:      SimConfig


def build_baseline() -> Alternative:
    return Alternative(
        name        = 'Baseline',
        cost        = 0,
        description = 'Current as-is festival configuration.',
        config      = baseline_config(),
    )


def build_combo_a() -> Alternative:
    """
    Combo A: Extra Photo+BodyArt + Popular Bands + Visitor Gift
    Cost: 150,000 + 300,000 + 200,000 = 650,000 NIS
    """
    cfg = baseline_config()
    cfg = alt_extra_photo_and_body_art(cfg)
    cfg = alt_popular_bands(cfg)
    cfg = alt_visitor_gift(cfg)
    return Alternative(
        name        = 'Combo_A',
        cost        = 150_000 + 300_000 + 200_000,
        description = (
            'Extra photo station (#4) + body art artist (#4) + '
            'popular mainstream bands (#3) + visitor gift bag (#7). '
            'Total cost: 650,000 NIS.'
        ),
        config      = cfg,
    )


def build_combo_b() -> Alternative:
    """
    Combo B: Better Kitchen + Marketing
    Cost: 500,000 + 200,000 = 700,000 NIS
    """
    cfg = baseline_config()
    cfg = alt_better_kitchen(cfg)
    cfg = alt_marketing(cfg)
    return Alternative(
        name        = 'Combo_B',
        cost        = 500_000 + 200_000,
        description = (
            'Better kitchen staff (#1) + marketing campaign (#5). '
            'Total cost: 700,000 NIS.'
        ),
        config      = cfg,
    )


def validate_budget(alternative: Alternative) -> bool:
    """Check that an alternative's cost does not exceed the budget limit."""
    if alternative.cost > BUDGET_LIMIT:
        raise ValueError(
            f"Alternative '{alternative.name}' exceeds budget: "
            f"{alternative.cost:,} > {BUDGET_LIMIT:,} NIS"
        )
    return True


ALL_ALTERNATIVES: Dict[str, Callable[[], Alternative]] = {
    'Baseline': build_baseline,
    'Combo_A':  build_combo_a,
    'Combo_B':  build_combo_b,
}
