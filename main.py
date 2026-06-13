
from __future__ import annotations

import argparse
import os
import sys
import time

# Make sure the project folder is on the import path
sys.path.insert(0, os.path.dirname(__file__))

from config import SimConfig
from engine import Simulation
from sim_stats import MultiRunStatistics, RunStatistics
from alternatives import (
    build_baseline, build_combo_a, build_combo_b, build_combo_c,
    ALL_ALTERNATIVES,
)
from distribution_fitting import fit_from_excel
from plotting import RunPlotter, KPIComparisonPlotter, plot_heating_time_data
from warmup import WarmupSimulation


# Constants ─────────────────────────────────────────────────────────────────────────────

EXCEL_PATH = os.path.join(os.path.dirname(__file__),
                          'samples_for_simulation.xlsx')

# Default number of replications per scenario. The user can override
# this with the --runs CLI flag.
DEFAULT_RUNS = 20

# Required by the project spec (p. 7): confidence level 0.9 (α = 0.1) and
# relative precision 0.1 for every comparison.
CONFIDENCE_LEVEL = 0.9
RELATIVE_PRECISION = 0.10

# KPIs we will optimise / compare across scenarios.
KPIS_TO_COMPARE = ['avg_satisfaction', 'total_revenue', 'avg_queue_length']

# For each KPI, is "higher" the better outcome?
# Used both in the recommendation (max vs min) and in the comparison
# arrows (better vs worse).
KPI_HIGHER_IS_BETTER = {
    'avg_satisfaction':   True,
    'total_revenue':      True,
    'avg_queue_length':   False,   # shorter queues = better
}


# Text helpers ─────────────────────────────────────────────────────────────────────────────

def section(title):
    """Print a visible section header to make the output scannable."""
    print("\n" + "=" * 70)
    print("  " + title)
    print("=" * 70)


def paragraph(text):
    """Print a wrapped explanatory paragraph (indented two spaces)."""
    for line in text.strip().splitlines():
        print("  " + line.strip())


# Scenario runner ─────────────────────────────────────────────────────────────────────────────

def run_scenario(name, cfg, num_runs, friends_sampler, main_stage_sampler,
                 verbose=False, base_seed=1000, plot=False):
    """
    Execute `num_runs` independent replications of the given scenario.

    Each replication:
        - starts a fresh Simulation
        - injects the fitted distribution samplers
        - seeds the RNG deterministically (base_seed + i)
        - runs the 2-day festival
        - returns a RunStatistics object summarising the run

    If `plot=True`, every run also saves a dashboard PNG to `plots/`.

    All scenarios share the same base_seed default, so run i of every
    scenario sees the same random stream → Common Random Numbers (CRN).
    That makes Welch's t-test slightly conservative but enables the paired
    t-test as a stronger alternative.
    """
    multi = MultiRunStatistics(CONFIDENCE_LEVEL, RELATIVE_PRECISION)
    print("\n  Running '{}' — {} replications ...".format(name, num_runs))

    for i in range(num_runs):
        t0 = time.time()
        sim = Simulation(
            cfg,
            friends_arrival_sampler=friends_sampler,
            main_stage_duration_sampler=main_stage_sampler,
            verbose=(verbose and i == 0),   # only log the first run
        )
        stats = sim.run(seed=base_seed + i)
        multi.add_run(stats)
        elapsed = time.time() - t0
        s = stats.summary()
        print("    Run {:3d}/{}  avg_sat={:.3f}  "
              "revenue={:,.0f} NIS  ({:.2f}s)".format(
                  i + 1, num_runs,
                  s['avg_satisfaction'], s['total_revenue_NIS'], elapsed))

        if plot:
            label = '{}_run{:02d}'.format(name, i + 1)
            RunPlotter(stats, name=label).plot_all(show=False, save=True)

    return multi


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


# Main routine ─────────────────────────────────────────────────────────────────────────────

def main(args):

    section("QUEUECHELLA FESTIVAL SIMULATION  —  Semester B 2026")

    paragraph("""
        Discrete-event simulation of a 2-day music festival.

        The model has 3 entity types (FriendsGroup, Couple, Single),
        6 service stations, and 3 concert stages.  The engine is
        event-driven: a min-heap of Event objects, each calling
        event.handle(simulation) when popped — same architecture as
        the example HotelSimulation project from Tutorial 6.
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

    baseline_alt = build_baseline()

    # ── Step 1.5: Warm-up (heating-time) analysis ────────────────────────────
    if args.warmup:
        section("[1.5] Warm-up period analysis")
        paragraph("""
            We run 30 independent replications and plot two KPIs
            (Average Queue Length and Average Satisfaction) over
            replication number.  Welch's moving-average smoother is
            overlaid to make the stabilisation point visible.

            For this finite-horizon festival simulation every replication
            starts from identical empty-system conditions, so we expect
            rapid stabilisation.  The warm-up cutoff is set to 5
            replications based on visual inspection of the plots.

            Run time = warm-up (5) x 7 + warm-up (5) = 40 replications
            are needed to collect sufficient steady-state data.
        """)
        sim = WarmupSimulation(30)
        sim.run()
        sim.plot_heating_time_data(sim.daily_avg_queue_lengths, 'Average Queue Length')
        sim.plot_heating_time_data(sim.daily_avg_satisfactions, 'Average Satisfaction')

    # ── Step 2: Full baseline run ────────────────────────────────────────────
    total_runs = args.runs if args.runs else DEFAULT_RUNS

    section("[2] Full baseline ({} replications)".format(total_runs))
    paragraph("""
        Run the baseline configuration `{}` times to get precise estimates
        of every KPI plus their {:.0f}% confidence intervals.
    """.format(total_runs, CONFIDENCE_LEVEL * 100))

    baseline_stats = run_scenario(
        name='Baseline',
        cfg=baseline_alt.config,
        num_runs=total_runs,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
        plot=args.plot,
    )
    print(baseline_stats.report())

    # ── Step 3: Alternative scenarios ────────────────────────────────────────
    section("[3] Alternative scenarios")
    paragraph("""
        We evaluate three budget-feasible combinations of the seven
        improvement options listed in the project brief (budget cap
        1,000,000 NIS). Each combo was selected from the exhaustive
        scan (see scan_alternatives.py) as the leader in one category:

          Combo_A = Extra photo+art (150k) + Marketing (200k)
                    + Auto ticket scanning (600k) = 950k NIS
                    OVERALL WINNER: best rank-sum across all 5 KPIs.

          Combo_B = Marketing (200k) + Auto ticket scanning (600k)
                    + Visitor gift bag (200k) = 1,000k NIS
                    REVENUE KING: highest total_revenue_NIS
                    in the scan (+46.7% vs baseline).

          Combo_C = Popular bands (300k) + Extra photo+art (150k)
                    + Visitor gift bag (200k) = 650k NIS
                    SATISFACTION KING: highest avg_satisfaction
                    in the scan (+31.1% vs baseline).

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
        plot=args.plot,
    )
    print(combo_a_stats.report())

    combo_b_alt = build_combo_b()
    combo_b_stats = run_scenario(
        name=combo_b_alt.name,
        cfg=combo_b_alt.config,
        num_runs=total_runs,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
        plot=args.plot,
    )
    print(combo_b_stats.report())

    combo_c_alt = build_combo_c()
    combo_c_stats = run_scenario(
        name=combo_c_alt.name,
        cfg=combo_c_alt.config,
        num_runs=total_runs,
        friends_sampler=friends_sampler,
        main_stage_sampler=main_stage_sampler,
        plot=args.plot,
    )
    print(combo_c_stats.report())

    # ── Step 4: Statistical comparison ───────────────────────────────────────
    section("[4] Statistical comparison (Welch's two-sample t-test)")
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
    print_comparison(baseline_stats, combo_c_stats, combo_c_alt.name)

    # ── Step 5: Recommendations ──────────────────────────────────────────────
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
            c_mean, *_ = combo_c_stats.confidence_interval(kpi)
            candidates = [
                ('Baseline', base_mean),
                (combo_a_alt.name, a_mean),
                (combo_b_alt.name, b_mean),
                (combo_c_alt.name, c_mean),
            ]
            selector = max if KPI_HIGHER_IS_BETTER.get(kpi, True) else min
            best = selector(candidates, key=lambda x: x[1])
            direction = "higher" if KPI_HIGHER_IS_BETTER.get(kpi, True) else "lower"
            print("  {:25s} ({}={:.4f})  best: {}".format(
                kpi, direction, best[1], best[0]))
        except Exception:
            pass

    print("=" * 70)

    # ── Step 6: KPI comparison plots ────────────────────────────────────────
    if args.plot:
        section("[5] KPI comparison plots")
        scenarios = {
            'Baseline':       baseline_stats,
            combo_a_alt.name: combo_a_stats,
            combo_b_alt.name: combo_b_stats,
            combo_c_alt.name: combo_c_stats,
        }
        KPIComparisonPlotter(
            scenarios,
            kpi_higher_better=KPI_HIGHER_IS_BETTER,
        ).plot_all_kpis(KPIS_TO_COMPARE, show=False, save=True)


# CLI entry point ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run the Queuechella Festival Simulation.')
    parser.add_argument('--runs', type=int, default=None,
                        help='Override number of simulation replications.')
    parser.add_argument('--verbose', action='store_true',
                        help='Print event log for the first run of each scenario.')
    parser.add_argument('--no-fit', action='store_true',
                        help='Skip Excel distribution fitting; use defaults.')
    parser.add_argument('--plot', action='store_true',
                        help='Save a per-run dashboard PNG to plots/ for every replication.')
    parser.add_argument('--warmup', action='store_true',
                        help='Run warm-up (heating-time) analysis before the main runs.')
    args = parser.parse_args()
    main(args)
