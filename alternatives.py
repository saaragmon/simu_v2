"""
alternatives.py
===============
Alternative scenario definitions and budget guard.

Budget cap: 1,000,000 NIS per combination.

Building blocks (from project spec):
    1. Better Kitchen Staff       – 500,000 NIS
    2. Expanded Security Team     – 650,000 NIS  (+30% stage capacity)
    3. Popular Mainstream Bands   – 300,000 NIS
    4. Extra Photo + Body Art     – 150,000 NIS
    5. Marketing Campaign         – 200,000 NIS  (+20% arrivals)
    6. Automatic Ticket Scanning  – 600,000 NIS  (no scan time)
    7. Visitor Gift Bag           – 200,000 NIS  (satisfaction starts at 6.5)

Three scenarios are exposed — one per-KPI winner:

    Combo_A — Satisfaction king (highest mean avg_satisfaction)
    Combo_B — Revenue king       (highest mean total_revenue_NIS)
    Combo_C — Queue king         (shortest mean avg_queue_length)

Each combo is just a list of block ids in `COMBO_SPECS`. Change them
to re-target the scenarios — cost, description and the SimConfig
chain are computed automatically by `_build_from_blocks`. Re-running
`scan_alternatives.py` and pasting the new winners into
`COMBO_SPECS` is the entire update path.

For notebooks: use `KPI_TO_COMBO[kpi]` to ask "which combo is the
best for KPI X".
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from config import (
    SimConfig,
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


# ─── Building blocks (id → name, cost, mutator) ──────────────────────────────
# Underscore-prefixed name avoids a collision with scan_alternatives.py's
# `BLOCKS` (a list of 4-tuples) when both modules are pasted into the same
# Jupyter notebook namespace.
_BLOCKS: Dict[int, Tuple[str, int, Callable[[SimConfig], SimConfig]]] = {
    1: ('Kitchen',   500_000, alt_better_kitchen),
    2: ('Security',  650_000, alt_expanded_security),
    3: ('Bands',     300_000, alt_popular_bands),
    4: ('PhotoArt',  150_000, alt_extra_photo_and_body_art),
    5: ('Marketing', 200_000, alt_marketing),
    6: ('AutoScan',  600_000, alt_auto_ticket_scan),
    7: ('Gift',      200_000, alt_visitor_gift),
}

# Backward-compat alias (do NOT use in code that may share a namespace
# with scan_alternatives.py).
BLOCKS = _BLOCKS


# ─── Combos: edit this dict to change which scenarios run ────────────────────
# Block ids reference BLOCKS above. The `optimizes` field is the KPI the
# combo was selected for ('overall' for the cross-KPI winner). The values
# below come from the current scan_alternatives.py output — re-run that
# script and update the block lists here if the scan winners change.

COMBO_SPECS: Dict[str, Dict] = {
    'Combo_A': {
        'blocks':    [1, 3, 7],
        'optimizes': 'avg_satisfaction',
        'tagline':   'Satisfaction king — highest mean avg_satisfaction',
    },
    'Combo_B': {
        'blocks':    [5, 6, 7],
        'optimizes': 'total_revenue',
        'tagline':   'Revenue king — highest mean total_revenue_NIS',
    },
    'Combo_C': {
        'blocks':    [6, 7],
        'optimizes': 'avg_queue_length',
        'tagline':   'Queue king — shortest mean avg_queue_length',
    },
}


# ─── Lookup tables generated from COMBO_SPECS ────────────────────────────────
# These stay in sync automatically — editing COMBO_SPECS is enough.

KPI_TO_COMBO: Dict[str, str] = {
    spec['optimizes']: name
    for name, spec in COMBO_SPECS.items()
}
"""Map every KPI → the name of the combo that wins it.
Example: KPI_TO_COMBO['avg_satisfaction'] → 'Combo_A'."""


@dataclass
class Alternative:
    """A single scenario: name, NIS cost, description, and SimConfig."""
    name:        str
    cost:        int
    description: str
    config:      SimConfig


# ─── Generic builder ─────────────────────────────────────────────────────────

def _build_from_blocks(name: str, block_ids: List[int],
                       tagline: str) -> Alternative:
    """Chain block mutators, sum their costs, and build the description."""
    cfg = baseline_config()
    parts: List[str] = []
    cost = 0
    for bid in block_ids:
        bname, bcost, mutator = _BLOCKS[bid]
        cfg = mutator(cfg)
        parts.append(f"{bname} (#{bid})")
        cost += bcost
    description = f"{' + '.join(parts)}. {tagline}. {cost:,} NIS."
    return Alternative(name=name, cost=cost,
                       description=description, config=cfg)


def build_baseline() -> Alternative:
    return Alternative(
        name        = 'Baseline',
        cost        = 0,
        description = 'Current as-is festival configuration.',
        config      = baseline_config(),
    )


def build_combo(name: str) -> Alternative:
    """Build any combo defined in COMBO_SPECS by its name."""
    if name not in COMBO_SPECS:
        raise KeyError(
            f"Unknown combo '{name}'. Known combos: "
            f"{list(COMBO_SPECS.keys())}"
        )
    spec = COMBO_SPECS[name]
    return _build_from_blocks(name, spec['blocks'], spec['tagline'])


# ─── Backward-compatible thin wrappers ───────────────────────────────────────
# Notebooks and main.py call these by name; the actual logic lives in
# build_combo(), so editing COMBO_SPECS is enough to retarget them.

def build_combo_a() -> Alternative:
    return build_combo('Combo_A')


def build_combo_b() -> Alternative:
    return build_combo('Combo_B')


def build_combo_c() -> Alternative:
    return build_combo('Combo_C')


# ─── Budget guard ────────────────────────────────────────────────────────────

def validate_budget(alternative: Alternative) -> bool:
    if alternative.cost > BUDGET_LIMIT:
        raise ValueError(
            f"Alternative '{alternative.name}' exceeds budget: "
            f"{alternative.cost:,} > {BUDGET_LIMIT:,} NIS"
        )
    return True


# ─── Registry consumed by main.py / notebooks ────────────────────────────────
# Generated from COMBO_SPECS so adding a new combo only requires extending
# COMBO_SPECS — this dict updates automatically.

ALL_ALTERNATIVES: Dict[str, Callable[[], Alternative]] = {
    'Baseline': build_baseline,
    **{name: (lambda n=name: build_combo(n)) for name in COMBO_SPECS},
}
