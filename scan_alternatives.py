"""
scan_alternatives.py
====================
Exhaustively evaluate every budget-feasible combination of the 7 alternatives
(34 combos of size >=2 under 1,000,000 NIS) plus baseline, with 5 replications
each. Report the best combo per KPI.
"""

from __future__ import annotations
import time
from itertools import combinations
from statistics import mean

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
from engine import Simulation


# Seven building blocks: (id, name, cost, mutator)
BLOCKS = [
    (1, 'Kitchen',     500_000, alt_better_kitchen),
    (2, 'Security',    650_000, alt_expanded_security),
    (3, 'Bands',       300_000, alt_popular_bands),
    (4, 'PhotoArt',    150_000, alt_extra_photo_and_body_art),
    (5, 'Marketing',   200_000, alt_marketing),
    (6, 'AutoScan',    600_000, alt_auto_ticket_scan),
    (7, 'Gift',        200_000, alt_visitor_gift),
]
BUDGET = 1_000_000
REPS = 5
BASE_SEED = 1000

KPIS = ['avg_satisfaction', 'total_revenue_NIS', 'avg_queue_length']
HIGHER_IS_BETTER = {
    'avg_satisfaction':   True,
    'total_revenue_NIS':  True,
    'avg_queue_length':   False,
}


def feasible_combos(min_size=2):
    """All non-empty subsets of BLOCKS with size>=min_size whose cost<=BUDGET."""
    out = []
    for size in range(min_size, len(BLOCKS) + 1):
        for combo in combinations(BLOCKS, size):
            cost = sum(b[2] for b in combo)
            if cost <= BUDGET:
                out.append(combo)
    return out


def build_config(combo):
    """Apply each block's mutator to a fresh baseline config."""
    cfg = baseline_config()
    for (_id, _name, _cost, mut) in combo:
        cfg = mut(cfg)
    return cfg


def combo_label(combo):
    return '{' + ','.join(str(b[0]) for b in combo) + '}'


def combo_descr(combo):
    return '+'.join(b[1] for b in combo)


def run_combo(combo, reps=REPS):
    """Run reps replications, return dict of KPI -> mean across reps."""
    cfg = build_config(combo) if combo else baseline_config()
    summaries = []
    for i in range(reps):
        sim = Simulation(cfg, verbose=False)
        stats = sim.run(seed=BASE_SEED + i)
        summaries.append(stats.summary())
    return {k: mean(s[k] for s in summaries) for k in KPIS}


def main():
    combos = feasible_combos(min_size=2)
    print(f'Evaluating Baseline + {len(combos)} budget-feasible combos '
          f'(size>=2, cost<={BUDGET:,}), {REPS} reps each. '
          f'Total runs = {(len(combos)+1) * REPS}.')
    t0 = time.time()

    # Baseline
    print('\n  Running Baseline ...', end=' ', flush=True)
    base_means = run_combo(None)
    print(f"sat={base_means['avg_satisfaction']:.3f}  "
          f"rev={base_means['total_revenue_NIS']:,.0f}  "
          f"qlen={base_means['avg_queue_length']:.1f}")

    # All feasible combos
    results = []  # list of (label, descr, cost, kpi_means_dict)
    for combo in sorted(combos, key=lambda c: -sum(b[2] for b in c)):
        cost = sum(b[2] for b in combo)
        means = run_combo(combo)
        results.append((combo_label(combo), combo_descr(combo), cost, means))
        print(f"  {combo_label(combo):14s} cost={cost:>7,}  "
              f"sat={means['avg_satisfaction']:.3f}  "
              f"rev={means['total_revenue_NIS']:,.0f}  "
              f"qlen={means['avg_queue_length']:.1f}")

    print(f'\nDone in {time.time()-t0:.1f}s.')

    # ─── Per-KPI winners ─────────────────────────────────────────────────────
    print('\n' + '=' * 70)
    print('  PER-KPI WINNERS (best combo vs baseline)')
    print('=' * 70)
    for kpi in KPIS:
        higher_better = HIGHER_IS_BETTER[kpi]
        selector = max if higher_better else min
        winner = selector(results, key=lambda r: r[3][kpi])
        baseline_val = base_means[kpi]
        delta = winner[3][kpi] - baseline_val
        delta_pct = 100 * delta / baseline_val if baseline_val else 0.0
        arrow = '↑' if higher_better else '↓'
        print(f"\n  {kpi}  ({arrow} better)")
        print(f"    Baseline:      {baseline_val:>12,.3f}")
        print(f"    Best combo:    {winner[0]} = {winner[1]}")
        print(f"    Cost:          {winner[2]:>12,} NIS")
        print(f"    Value:         {winner[3][kpi]:>12,.3f}")
        print(f"    Δ vs baseline: {delta:+,.3f} ({delta_pct:+.1f}%)")


if __name__ == '__main__':
    main()
