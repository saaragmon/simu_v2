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

Combinations currently configured (all within the 1,000,000 NIS budget):
    Combo_A = #4 + #5 + #6  (PhotoArt + Marketing + AutoScan)   = 950k
              Exhaustive-scan OVERALL WINNER — best rank-sum across
              all 5 KPIs. See scan_alternatives.py for methodology.
    Combo_B = #5 + #6 + #7  (Marketing + AutoScan + Gift)       = 1,000k
              REVENUE KING — highest mean total_revenue_NIS in the
              scan (+46.7% vs baseline).
    Combo_C = #3 + #4 + #7  (Bands + PhotoArt + Gift)           = 650k
              SATISFACTION KING — highest mean avg_satisfaction in
              the scan (+31.1% vs baseline).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List

from config import SimConfig
from config import (
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
    Combo A: Extra Photo+BodyArt + Marketing + Automatic Ticket Scanning
    Cost: 150,000 + 200,000 + 600,000 = 950,000 NIS

    OVERALL WINNER from the exhaustive scan: lowest rank-sum across all
    5 KPIs (avg_satisfaction, avg_visit_duration, total_revenue_NIS,
    total_entities, avg_queue_length).

    Mechanism:
      • Auto-scan (#6) removes the entry-gate bottleneck.
      • Extra photo & body-art (#4) shortens service queues.
      • Marketing (#5) feeds more visitors into the now-uncongested system,
        boosting revenue and throughput.
    """
    cfg = baseline_config()
    cfg = alt_extra_photo_and_body_art(cfg)
    cfg = alt_marketing(cfg)
    cfg = alt_auto_ticket_scan(cfg)
    return Alternative(
        name        = 'Combo_A',
        cost        = 150_000 + 200_000 + 600_000,
        description = (
            'Extra photo+body-art (#4) + marketing (#5) + '
            'auto ticket scanning (#6). Overall scan winner. '
            'Total cost: 950,000 NIS.'
        ),
        config      = cfg,
    )


def build_combo_b() -> Alternative:
    """
    Combo B: Marketing + Automatic Ticket Scanning + Visitor Gift
    Cost: 200,000 + 600,000 + 200,000 = 1,000,000 NIS

    REVENUE KING — the combination that maximises total_revenue_NIS
    in the exhaustive scan: +46.7% vs baseline (2,203,190 NIS vs
    1,501,834 NIS baseline).

    Mechanism:
      • Marketing (#5) brings +20% more visitors → more wallets through
        the gate.
      • Auto-scan (#6) keeps that extra demand from clogging the entry
        queue → more visitors actually reach the merch tent / food stalls.
      • Gift bag (#7) raises starting satisfaction → fewer abandonments
        before purchase.
    """
    cfg = baseline_config()
    cfg = alt_marketing(cfg)
    cfg = alt_auto_ticket_scan(cfg)
    cfg = alt_visitor_gift(cfg)
    return Alternative(
        name        = 'Combo_B',
        cost        = 200_000 + 600_000 + 200_000,
        description = (
            'Marketing (#5) + auto ticket scanning (#6) + '
            'visitor gift bag (#7). Best for revenue. '
            'Total cost: 1,000,000 NIS.'
        ),
        config      = cfg,
    )


def build_combo_c() -> Alternative:
    """
    Combo C: Popular Bands + Extra Photo+BodyArt + Visitor Gift
    Cost: 300,000 + 150,000 + 200,000 = 650,000 NIS

    SATISFACTION KING — the combination that maximises avg_satisfaction
    in the exhaustive scan: +31.1% vs baseline (6.77 vs 5.17 baseline).

    Mechanism:
      • Bands (#3) raises the genre-weight term in the satisfaction
        formula from 3 to 4 — a direct, formula-level lift.
      • Photo + body-art (#4) shortens the busiest service queues, so
        fewer satisfaction penalties from waiting.
      • Gift bag (#7) starts every visitor at satisfaction 6.5 instead
        of 5.0 — a 30% head start before any in-festival effects.
    """
    cfg = baseline_config()
    cfg = alt_popular_bands(cfg)
    cfg = alt_extra_photo_and_body_art(cfg)
    cfg = alt_visitor_gift(cfg)
    return Alternative(
        name        = 'Combo_C',
        cost        = 300_000 + 150_000 + 200_000,
        description = (
            'Popular bands (#3) + extra photo+body-art (#4) + '
            'visitor gift bag (#7). Best for satisfaction. '
            'Total cost: 650,000 NIS.'
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
    'Combo_C':  build_combo_c,
}
