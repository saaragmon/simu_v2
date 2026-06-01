"""
main.py
=======
Entry point for the Queuechella Festival Simulation.

This script is the "front desk" of the simulation. It:
    1. Loads the Excel sample data and fits distributions
       (Exponential / Normal / Uniform via KS goodness-of-fit).
    2. Runs a small PILOT study on the baseline configuration.
    3. Uses the pilot variance to estimate how many replications are
       needed for relative precision δ at confidence level 1 - α.
    4. Runs that many replications of the BASELINE and of each
       ALTERNATIVE combination.
    5. Builds Student-t confidence intervals for every KPI.
    6. Compares each alternative to the baseline with Welch's two-sample
       t-test (independent samples; no Common Random Numbers).
    7. Picks the best alternative per KPI, respecting which direction is
       "better" (e.g. higher satisfaction good, lower visit duration good).

Usage:
    python main.py                          # default end-to-end run
    python main.py --runs 30                # override replication count
    python main.py --verbose                # print event log for first run
    python main.py --no-fit                 # skip Excel fitting, use defaults
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Make sure the project folder is on the import path
sys.path.insert(0, os.path.dirname(__file__))

from config import SimConfig
from engine import SimulationEngine
from sim_stats import MultiRunStatistics, RunStatistics
from alternatives import (
    build_baseline, build_combo_a, build_combo_b, ALL_ALTERNATIVES
)
from distribution_fitting import fit_from_excel


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

EXCEL_PATH = os.path.join(os.path.dirname(__file__),
                          'samples_for_simulation.xlsx')

# Pilot study: a small batch used to estimate the variance of the KPI
# we want to control. Five replications is a common starting point.
PILOT_RUNS = 5

# Required by the project spec: confidence level 0.9 and relative
# precision 0.1 for every comparison.
CONFIDENCE_LEVEL = 0.90
RELATIVE_PRECISION = 0.10

# KPIs we will optimise / compare across scenarios.
KPIS_TO_COMPARE = ['avg_satisfaction', 'avg_visit_duration', 'total_revenue']

# For each KPI, is "higher" the better outcome?
# Used both in the recommendation (max vs min) and in the comparison
# arrows (better vs worse).
KPI_HIGHER_IS_BETTER = {
    'avg_satisfaction':   True,
    'avg_visit_duration': False,   # less time stuck in queues = better
    'total_revenue':      True,
    'total_entities':     True,
}


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────────────────────────────────────

def section(title):
    """Print a visible section header to make the output scannable."""
    print("\n" + "=" * 70)
    print("  " + title)
    print("=" * 70)


def paragraph(text):
    """Print a wrapped explanatory paragraph (indented two spaces)."""
    for line in text.strip().splitlines():
        print("  " + line.strip())


# ─────────────────────────────────────────────────────────────────────────────
# Scenario runner
# ─────────────────────────────────────────────────────────────────────────────

def run_scenario(name, cfg, num_runs, friends_sampler, main_stage_sampler,
                 verbose=False, base_seed=1000):
    """
    Execute `num_runs` independent replications of the given scenario.

    Each replication:
        - starts a fresh SimulationEngine
        - injects the fitted distribution samplers
        - seeds the RNG deterministically (base_seed + i)
        - runs the 2-day festival
        - returns a RunStatistics object summarising the run

    All scenarios share the same base_seed default, so run i of every
    scenario sees the same random stream → Common Random Numbers (CRN).
    That makes Welch's t-test slightly conservative but enables the paired
    t-test as a stronger alternative.
    """
    multi = MultiRunStatistics(CONFIDENCE_LEVEL, RELATIVE_PRECISION)
    print("\n  Running '{}' — {} replications ...".format(name, num_runs))

    for i in range(num_runs):
        t0 = time.time()
        engine = SimulationEngine(
            cfg,
            friends_arrival_sampler=friends_sampler,
            main_stage_duration_sampler=main_stage_sampler,
            verbose=(verbose and i == 0),   # only log the first run
        )
        stats = engine.run(seed=base_seed + i)
        multi.add_run(stats)
        elapsed = time.time() - t0
        s = stats.summary()
        print("    Run {:3d}/{}  entities={:4d}  avg_sat={:.3f}  "
              "revenue={:,.0f} NIS  ({:.2f}s)".format(
                  i + 1, num_runs, s['total_entities'],
                  s['avg_satisfaction'], s['total_revenue_NIS'], elapsed))

    return multi


def determine_required_runs(pilot_results, kpi='avg_satisfaction'):
    """
    Use the pilot variance to compute n* via the standard formula:

        n* = ceil( (t_{α/2, n0-1} * s / (δ * x_bar))^2 )

    Returns at least the pilot-runs count.
    """
    return pilot_results.required_replications(kpi, pilot_runs=PILOT_RUNS)


def print_comparison(baseline, alternative, alt_name):
    """
    Compare one alternative scenario against the baseline using Welch's
    two-sample t-test (appropriate for independent samples).

    Reports per KPI:
        - t-statistic
        - critical value t_{α/2, df}
        - whether the difference is statistically significant
        - whether the alternative is BETTER (↑) or WORSE (↓) than the
          baseline, accounting for the KPI's direction.
    """
    print("\n  --- {} vs Baseline (Welch's t-test) ---".format(alt_name))
    for kpi in KPIS_TO_COMPARE:
        try:
            # diffs are computed as (baseline - alt), so:
            # t_stat < 0  =>  alt is HIGHER than baseline
            t_stat, t_crit, reject = baseline.welch_t_test(alternative, kpi)
            alt_is_higher = t_stat < 0
            higher_is_better = KPI_HIGHER_IS_BETTER.get(kpi, True)
            alt_is_better = (alt_is_higher == higher_is_better)
            direction = "↑ better" if alt_is_better else "↓ worse"
            verdict = "SIGNIFICANT" if reject else "not significant"
            print("    {:25s}: t={:+7.3f}  t_crit={:.3f}  -> {} {}".format(
                kpi, t_stat, t_crit, verdict,
                direction if reject else ""))
        except Exception as e:
            print("    {}: ERROR — {}".format(kpi, e))


# ─────────────────────────────────────────────────────────────────────────────
# Main routine
# ─────────────────────────────────────────────────────────────────────────────

def main(args):

    section("QUEUECHELLA FESTIVAL SIMULATION  —  Semester B 2026")

    paragraph("""
        Discrete-event simulation of a 2-day music festival.

        The model has 3 entity types (FriendsGroup, Couple, Single),
        6 service stations, and 3 concert stages.  The engine is
        event-driven: a min-heap of Event objects, each calling
        event.handle(sim) when popped — same architecture as the
        example HotelSimulation project from Tutorial 6.
    """)

    # ── Step 1: Distribution fitting ─────────────────────────────────────────
    section("[1] Distribution fitting")
    paragraph("""
        Two columns of sample data live in `samples_for_simulation.xlsx`:
          - Sheet 1: inter-arrival times of FriendsGroup
          - Sheet 2: MainStage show durations

        For each, we fit three candidate distributions
        (Exponential, Normal, Uniform) by MLE and select the one with
        the smallest Kolmogorov-Smirnov statistic
        D = max_x |F_empirical(x) - F_theoretical(x)|.

        The selected sampler is then injected into the engine and used
        for every replication below.
    """)

    friends_sampler = None
    main_stage_sampler = None

    if not args.no_fit and os.path.exists(EXCEL_PATH):
        print("\n  Reading: {}".format(EXCEL_PATH))
        samplers = fit_from_excel(EXCEL_PATH)
        friends_sampler = samplers.get('friends_interarrival')
        main_stage_sampler = samplers.get('main_stage_duration')
    else:
        print("\n  Skipping Excel fitting — using built-in defaults.")

    # ── Step 2: Pilot study ──────────────────────────────────────────────────
    section("[2] Pilot study (baseline)")
    paragraph("""
        We first run a short pilot ({} replications) of the baseline.
        Its only purpose is to estimate the sample variance s^2 of
        avg_satisfaction so that we can compute how many additional
        replications are needed for a relative precision of δ = {}
        at confidence level 1 - α = {}.
    """.format(PILOT_RUNS, RELATIVE_PRECISION, CONFIDENCE_LEVEL))

    baseline_alt = build_baseline()
    pilot_results = run_scenario(
        name='Baseline (pilot)',
        cfg=baseline_alt.config,
        num_runs=PILOT_RUNS,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
        verbose=args.verbose,
    )

    # ── Step 3: Determine required replications ──────────────────────────────
    section("[3] Required number of replications")
    paragraph("""
        Formula (Banks et al., Discrete-Event System Simulation):

            n* = ceil( ( t_{α/2, n0-1} * s / ( δ * x_bar ) )^2 )

        with n0 = pilot size, s = pilot std, x_bar = pilot mean of
        the chosen KPI (avg_satisfaction here).
    """)

    if args.runs:
        required_runs = args.runs
        print("\n  Using user-specified replication count: {}".format(
            required_runs))
    else:
        required_runs = determine_required_runs(pilot_results)
        print("\n  n* = {}  (α={}, δ={})".format(
            required_runs, 1 - CONFIDENCE_LEVEL, RELATIVE_PRECISION))

    total_runs = max(required_runs, PILOT_RUNS)

    # ── Step 4: Full baseline run ────────────────────────────────────────────
    section("[4] Full baseline ({} replications)".format(total_runs))
    paragraph("""
        Now run the baseline configuration `total_runs` times to get
        precise estimates of every KPI plus their confidence intervals.
    """)

    baseline_stats = run_scenario(
        name='Baseline',
        cfg=baseline_alt.config,
        num_runs=total_runs,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
    )
    print(baseline_stats.report())

    # ── Step 5: Alternative scenarios ────────────────────────────────────────
    section("[5] Alternative scenarios")
    paragraph("""
        We picked two budget-feasible combinations of the seven
        improvement options listed in the project brief (budget cap
        1,000,000 NIS):

          Combo_A = Extra photo+art (150k) + Popular bands (300k)
                    + Visitor gift bag (200k) = 650k NIS
                    Hypothesis: large satisfaction boost.

          Combo_B = Better kitchen staff (500k) + Marketing (200k)
                    = 700k NIS
                    Hypothesis: higher throughput and revenue.

        Each combo is simulated with the same number of replications
        as the baseline so the comparisons are fair.
    """)

    combo_a_alt = build_combo_a()
    combo_a_stats = run_scenario(
        name=combo_a_alt.name,
        cfg=combo_a_alt.config,
        num_runs=total_runs,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
    )
    print(combo_a_stats.report())

    combo_b_alt = build_combo_b()
    combo_b_stats = run_scenario(
        name=combo_b_alt.name,
        cfg=combo_b_alt.config,
        num_runs=total_runs,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
    )
    print(combo_b_stats.report())

    # ── Step 6: Statistical comparison ───────────────────────────────────────
    section("[6] Statistical comparison (Welch's two-sample t-test)")
    paragraph("""
        Welch's t-test is appropriate because the replications across
        scenarios are independent (no Common Random Numbers).  Test
        statistic:

            t = (x_bar_baseline - x_bar_alt)
                / sqrt(s_baseline^2 / n + s_alt^2 / n)

        with degrees of freedom given by the Welch-Satterthwaite
        equation.  We reject H0 (means equal) at confidence 1 - α
        when |t| > t_{α/2, df}.
    """)

    print_comparison(baseline_stats, combo_a_stats, combo_a_alt.name)
    print_comparison(baseline_stats, combo_b_stats, combo_b_alt.name)

    # ── Step 7: Recommendations ──────────────────────────────────────────────
    section("FINAL RECOMMENDATIONS")
    paragraph("""
        For each KPI we report which scenario delivered the best mean,
        respecting whether higher or lower is the desired direction.
    """)

    for kpi in KPIS_TO_COMPARE:
        try:
            base_mean, *_ = baseline_stats.confidence_interval(kpi)
            a_mean, *_ = combo_a_stats.confidence_interval(kpi)
            b_mean, *_ = combo_b_stats.confidence_interval(kpi)
            candidates = [
                ('Baseline', base_mean),
                (combo_a_alt.name, a_mean),
                (combo_b_alt.name, b_mean),
            ]
            selector = max if KPI_HIGHER_IS_BETTER.get(kpi, True) else min
            best = selector(candidates, key=lambda x: x[1])
            direction = "higher" if KPI_HIGHER_IS_BETTER.get(kpi, True) else "lower"
            print("  {:25s} ({}={:.4f})  best: {}".format(
                kpi, direction, best[1], best[0]))
        except Exception:
            pass

    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run the Queuechella Festival Simulation.')
    parser.add_argument('--runs', type=int, default=None,
                        help='Override number of simulation replications.')
    parser.add_argument('--verbose', action='store_true',
                        help='Print event log for the first run of each scenario.')
    parser.add_argument('--no-fit', action='store_true',
                        help='Skip Excel distribution fitting; use defaults.')
    args = parser.parse_args()
    main(args)
