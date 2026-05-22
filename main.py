"""
main.py
=======
Entry point for the Queuechella Festival Simulation. 

Run this script directly to:

    1. Fit distributions from the Excel sample data.
    2. Execute the baseline simulation for the required number of replications.
    3. Run the two alternative scenario combinations.
    4. Compare alternatives via paired t-tests and confidence intervals.
    5. Print a final recommendation report.

Usage:
    python main.py                          # Run with default settings
    python main.py --runs 30               # Override replication count
    python main.py --verbose               # Print event-level log (slow)
    python main.py --no-fit                # Skip Excel fitting, use defaults
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# ── Ensure the package root is on sys.path when running from the project folder
sys.path.insert(0, os.path.dirname(__file__))

from config              import SimConfig
from engine              import SimulationEngine
from sim_stats           import MultiRunStatistics, RunStatistics
from alternatives        import (
    build_baseline, build_combo_a, build_combo_b, ALL_ALTERNATIVES
)
from distribution_fitting import fit_from_excel


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

EXCEL_PATH       = os.path.join(os.path.dirname(__file__),
                                'samples_for_simulation.xlsx')
PILOT_RUNS       = 5          # Initial runs used to estimate required replications
CONFIDENCE_LEVEL = 0.90
RELATIVE_PRECISION = 0.10
KPIS_TO_COMPARE  = ['avg_satisfaction', 'avg_sojourn_min', 'total_revenue']


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_scenario(name: str,
                 cfg: SimConfig,
                 num_runs: int,
                 friends_sampler,
                 main_stage_sampler,
                 verbose: bool = False) -> MultiRunStatistics:
    """Execute `num_runs` replications for a given scenario configuration."""
    multi = MultiRunStatistics(CONFIDENCE_LEVEL, RELATIVE_PRECISION)
    print(f"\n  Running '{name}' – {num_runs} replications …")

    for i in range(num_runs):
        t0     = time.time()
        engine = SimulationEngine(
            cfg,
            friends_arrival_sampler     = friends_sampler,
            main_stage_duration_sampler = main_stage_sampler,
            verbose                     = verbose and i == 0,   # log only first run
        )
        stats  = engine.run()
        multi.add_run(stats)
        elapsed = time.time() - t0
        summary = stats.summary()
        print(f"    Run {i+1:3d}/{num_runs}  "
              f"entities={summary['total_entities']:4d}  "
              f"avg_sat={summary['avg_satisfaction']:.3f}  "
              f"revenue={summary['total_revenue_NIS']:,.0f} NIS  "
              f"({elapsed:.2f}s)")

    return multi


def determine_required_runs(pilot_results: MultiRunStatistics,
                             kpi: str = 'avg_satisfaction') -> int:
    """
    Use pilot study to determine statistically sufficient replication count.
    """
    return pilot_results.required_replications(kpi, pilot_runs=PILOT_RUNS)


def print_comparison(baseline: MultiRunStatistics,
                     alternative: MultiRunStatistics,
                     alt_name: str) -> None:
    """Print paired t-test results comparing one alternative to the baseline."""
    print(f"\n  ─── {alt_name} vs Baseline ───")
    for kpi in KPIS_TO_COMPARE:
        try:
            t_stat, t_crit, reject = baseline.paired_t_test(alternative, kpi)
            direction = '↑' if t_stat < 0 else '↓'
            verdict   = 'SIGNIFICANT' if reject else 'not significant'
            print(f"    {kpi:25s}: t={t_stat:+6.3f}  t_crit={t_crit:.3f}  "
                  f"→ {verdict} {direction if reject else ''}")
        except Exception as e:
            print(f"    {kpi}: ERROR – {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main routine
# ─────────────────────────────────────────────────────────────────────────────

def main(args: argparse.Namespace) -> None:

    print("=" * 70)
    print("  QUEUECHELLA FESTIVAL SIMULATION  –  Semester B 2026")
    print("=" * 70)

    # ── Step 1: Distribution fitting ─────────────────────────────────────────
    friends_sampler      = None
    main_stage_sampler   = None

    if not args.no_fit and os.path.exists(EXCEL_PATH):
        print(f"\n[1] Fitting distributions from: {EXCEL_PATH}")
        samplers             = fit_from_excel(EXCEL_PATH)
        friends_sampler      = samplers.get('friends_interarrival')
        main_stage_sampler   = samplers.get('main_stage_duration')
    else:
        print("\n[1] Skipping Excel fitting – using default distributions.")

    # ── Step 2: Pilot study (baseline) ────────────────────────────────────────
    print("\n[2] Pilot study – running baseline …")
    baseline_alt  = build_baseline()
    pilot_results = run_scenario(
        name               = 'Baseline (pilot)',
        cfg                = baseline_alt.config,
        num_runs           = PILOT_RUNS,
        friends_sampler    = friends_sampler,
        main_stage_sampler = main_stage_sampler,
        verbose            = args.verbose,
    )

    # ── Step 3: Determine required replications ───────────────────────────────
    if args.runs:
        required_runs = args.runs
        print(f"\n[3] Using user-specified replication count: {required_runs}")
    else:
        required_runs = determine_required_runs(pilot_results)
        print(f"\n[3] Estimated required replications: {required_runs} "
              f"(α={1-CONFIDENCE_LEVEL:.2f}, δ={RELATIVE_PRECISION:.2f})")

    total_runs = max(required_runs, PILOT_RUNS)

    # ── Step 4: Full baseline run ──────────────────────────────────────────────
    print(f"\n[4] Full baseline simulation ({total_runs} runs) …")
    baseline_stats = run_scenario(
        name               = 'Baseline',
        cfg                = baseline_alt.config,
        num_runs           = total_runs,
        friends_sampler    = friends_sampler,
        main_stage_sampler = main_stage_sampler,
    )
    print(baseline_stats.report())

    # ── Step 5: Alternative scenarios ─────────────────────────────────────────
    print(f"\n[5] Running alternative scenarios …")

    combo_a_alt   = build_combo_a()
    combo_a_stats = run_scenario(
        name               = combo_a_alt.name,
        cfg                = combo_a_alt.config,
        num_runs           = total_runs,
        friends_sampler    = friends_sampler,
        main_stage_sampler = main_stage_sampler,
    )
    print(combo_a_stats.report())

    combo_b_alt   = build_combo_b()
    combo_b_stats = run_scenario(
        name               = combo_b_alt.name,
        cfg                = combo_b_alt.config,
        num_runs           = total_runs,
        friends_sampler    = friends_sampler,
        main_stage_sampler = main_stage_sampler,
    )
    print(combo_b_stats.report())

    # ── Step 6: Statistical comparison ────────────────────────────────────────
    print(f"\n[6] Statistical comparison (confidence level={CONFIDENCE_LEVEL*100:.0f}%)")
    print_comparison(baseline_stats, combo_a_stats, combo_a_alt.name)
    print_comparison(baseline_stats, combo_b_stats, combo_b_alt.name)

    # ── Step 7: Recommendations ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  FINAL RECOMMENDATIONS")
    print("=" * 70)
    for kpi in KPIS_TO_COMPARE:
        try:
            base_mean, *_  = baseline_stats.confidence_interval(kpi)
            a_mean, *_     = combo_a_stats.confidence_interval(kpi)
            b_mean, *_     = combo_b_stats.confidence_interval(kpi)
            best = max([('Baseline', base_mean),
                        (combo_a_alt.name, a_mean),
                        (combo_b_alt.name, b_mean)],
                       key=lambda x: x[1])
            print(f"  {kpi:25s}: Best = {best[0]}  ({best[1]:.4f})")
        except Exception:
            pass
    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run the Queuechella Festival Simulation.')
    parser.add_argument('--runs',    type=int,  default=None,
                        help='Override number of simulation replications.')
    parser.add_argument('--verbose', action='store_true',
                        help='Print event log for the first run of each scenario.')
    parser.add_argument('--no-fit',  action='store_true',
                        help='Skip Excel distribution fitting; use defaults.')
    args = parser.parse_args()
    main(args)
