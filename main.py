
from __future__ import annotations

import argparse
import math
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
from distributions import fit_from_excel
from plotting import RunPlotter, KPIComparisonPlotter, plot_heating_time_data
from warmup import WarmupSimulation


# Constants ─────────────────────────────────────────────────────────────────────────────

EXCEL_PATH = os.path.join(os.path.dirname(__file__),
                          'samples_for_simulation.xlsx')

# Default number of replications per scenario. The user can override
# this with the --runs CLI flag.
DEFAULT_RUNS = 20

# Pilot study size for variance estimation (Tutorial 10, steel-plant
# example uses n0=15).
PILOT_RUNS = 15

# Common Random Numbers base seed. All scenarios use the same seed
# so replication i shares the RNG stream across scenarios → paired t-test.
CRN_BASE_SEED = 1000

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

    All scenarios are called with the SAME `base_seed`, so replication i
    of every scenario draws from the same RNG stream — this is Common
    Random Numbers (CRN), the precondition for the paired t-test (see
    Tutorial 10, slide 17). Inducing positive correlation between paired
    runs reduces Var(x_i − y_i) and gives a more powerful test.
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
              "revenue={:,.0f} NIS  qlen={:.2f}  ({:.2f}s)".format(
                  i + 1, num_runs,
                  s['avg_satisfaction'], s['total_revenue_NIS'],
                  s['avg_queue_length'], elapsed))

        if plot:
            label = '{}_run{:02d}'.format(name, i + 1)
            RunPlotter(stats, name=label).plot_all(show=False, save=True)

    return multi


def print_comparison(baseline, alternative, alt_name, alpha_per_test=None):
    """
    Compare one alternative scenario against the baseline using the
    paired two-sample t-test (Tutorial 10, slides 8–10). This is the
    correct test under CRN: replication i in both scenarios shares the
    same RNG stream, so the differences z_i = x_i − y_i have lower
    variance than independent samples.

    Reports per KPI:
        - mean of paired differences (baseline - alternative)
        - confidence interval on the difference
        - verdict by checking whether 0 is inside the interval

    Pass `alpha_per_test` to apply a Bonferroni-corrected level
    (e.g. alpha_total / K) so the family-wise confidence is preserved.
    """
    if alpha_per_test is None:
        conf_pct = int(round(CONFIDENCE_LEVEL * 100))
    else:
        conf_pct = round((1 - alpha_per_test) * 100, 2)
    print("\n  --- {} vs Baseline (paired t-test, CRN) ---".format(alt_name))
    for kpi in KPIS_TO_COMPARE:
        try:
            r = baseline.paired_t_test(alternative, kpi, alpha=alpha_per_test)
            diff = r['diff']         # baseline − alternative
            lo, hi = r['ci_lower'], r['ci_upper']
            higher_is_better = KPI_HIGHER_IS_BETTER.get(kpi, True)

            print("    {}".format(kpi))
            print("      Mean difference (baseline - {}): {:+.4f}".format(
                alt_name, diff))
            print("      {}% Confidence Interval: [{:+.4f}, {:+.4f}]".format(
                conf_pct, lo, hi))

            if lo > 0:
                winner = 'Baseline' if higher_is_better else alt_name
                print("      0 outside CI → {} significantly better".format(winner))
            elif hi < 0:
                winner = alt_name if higher_is_better else 'Baseline'
                print("      0 outside CI → {} significantly better".format(winner))
            else:
                print("      0 inside CI → cannot determine which is better")
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

    # ── Step 1.7: Pilot study + required-runs calculation ────────────────────
    # K = (#alternatives compared to baseline) × (#KPIs) — same K used
    # later in Step 4 for the Bonferroni-corrected comparison.
    n_alternatives = 3
    K = n_alternatives * len(KPIS_TO_COMPARE)
    alpha_bonf = MultiRunStatistics.bonferroni_alpha(1 - CONFIDENCE_LEVEL, K)

    if args.runs:
        total_runs = args.runs
        section("[1.7] Pilot study (skipped — --runs={} forces n)".format(args.runs))
        paragraph("""
            User supplied --runs explicitly, so the pilot-based n*
            calculation is bypassed.
        """)
    else:
        section("[1.7] Pilot study & required-runs (n*)")
        paragraph("""
            Tutorial 10 (slide 6) prescribes a two-step procedure for
            sizing the replication count:

              1. Run n0 = {} pilot replications, estimate s and x_bar
                 for every KPI.
              2. Compute the required count:

                    n* = ceil( (t_{{α/2, n0-1}} · s / (γ' · x_bar))^2 )

                 where γ' = γ / (1 + γ) and γ = {:.2f} is the relative
                 precision goal.

            We use the Bonferroni-corrected α (α_total / K = {:.4f} / {}
            = {:.5f}) so that the precision goal respects family-wise
            confidence across all comparisons.

            Final n is max(n*) across the {} KPIs (we need every KPI
            to meet the precision goal).
        """.format(PILOT_RUNS, RELATIVE_PRECISION,
                   1 - CONFIDENCE_LEVEL, K, alpha_bonf,
                   len(KPIS_TO_COMPARE)))

        pilot_stats = run_scenario(
            name='Baseline_pilot',
            cfg=baseline_alt.config,
            num_runs=PILOT_RUNS,
            friends_sampler=friends_sampler,
            main_stage_sampler=main_stage_sampler,
            base_seed=CRN_BASE_SEED,
            plot=False,
        )

        per_kpi_n = {}
        for kpi in KPIS_TO_COMPARE:
            n_needed = pilot_stats.required_replications(
                kpi, pilot_runs=PILOT_RUNS, alpha=alpha_bonf)
            per_kpi_n[kpi] = n_needed
            print("    {:25s}  n* = {:4d}".format(kpi, n_needed))

        total_runs = max(max(per_kpi_n.values()), PILOT_RUNS)
        print("\n  → Using n = max(n*) = {} replications per scenario".format(
            total_runs))

    # ── Step 2: Full baseline run ────────────────────────────────────────────

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
        base_seed=CRN_BASE_SEED,
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
        base_seed=CRN_BASE_SEED,
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
        base_seed=CRN_BASE_SEED,
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
        base_seed=CRN_BASE_SEED,
        plot=args.plot,
    )
    print(combo_c_stats.report())

    # ── Step 3.5: Relative-precision verification ────────────────────────────
    section("[3.5] Relative-precision verification")
    paragraph("""
        After the full runs we verify the relative-precision criterion
        for every scenario × KPI (Hotel example; Tutorial 10 slide 5):

            relative_error = t_{{α/2, n-1}} · s / (sqrt(n) · |x_bar|)
            threshold      = γ / (1 + γ) = {:.4f}
            criterion      = relative_error ≤ threshold

        α here is the Bonferroni-corrected α_total / K so the precision
        budget is respected family-wise. If any cell fails the criterion,
        n* was an under-estimate (often happens when the pilot variance
        was unrepresentative); top up the runs and re-check.
    """.format(RELATIVE_PRECISION / (1 + RELATIVE_PRECISION)))

    all_scenarios = {
        'Baseline':       baseline_stats,
        combo_a_alt.name: combo_a_stats,
        combo_b_alt.name: combo_b_stats,
        combo_c_alt.name: combo_c_stats,
    }

    failed = []
    print("\n  {:18s}  {:25s}  {:>12s}  {:>12s}  {}".format(
        "Scenario", "KPI", "rel_error", "threshold", "meets"))
    for scen_name, stats_obj in all_scenarios.items():
        for kpi in KPIS_TO_COMPARE:
            try:
                r = stats_obj.relative_precision_check(kpi, alpha=alpha_bonf)
                mark = "✓" if r['meets'] else "✗"
                print("  {:18s}  {:25s}  {:>12.4f}  {:>12.4f}  {}".format(
                    scen_name, kpi, r['relative_error'], r['threshold'], mark))
                if not r['meets']:
                    failed.append((scen_name, kpi, r))
            except Exception as e:
                print("  {:18s}  {:25s}  ERROR — {}".format(scen_name, kpi, e))

    if failed:
        print("\n  ⚠  {} cell(s) failed the criterion.".format(len(failed)))
        # Solve n_new from: relative_error_now * sqrt(n) = threshold * sqrt(n_new)
        # ⇒ n_new = n * (rel_error / threshold)^2
        worst_scaling = max(
            (r['relative_error'] / r['threshold']) ** 2 for _, _, r in failed
        )
        n_top_up = math.ceil(total_runs * worst_scaling)
        print("  Suggested top-up: increase replications "
              "{} → {} (factor = {:.2f}).".format(
                  total_runs, n_top_up, worst_scaling))
        print("  Re-run with `python3 main.py --runs {}`.".format(n_top_up))
    else:
        print("\n  ✓  All KPIs in all scenarios meet the relative-precision goal.")

    # ── Step 4: Statistical comparison ───────────────────────────────────────
    section("[4] Statistical comparison (paired t-test, CRN)")
    paragraph("""
        Replications i across scenarios share an RNG stream (CRN), so
        the paired t-test from Tutorial 10 (slides 8–10) applies. Define
        z_i = x_baseline,i − x_alt,i; test:

            t = mean(z) / (s_z / sqrt(n))      df = n − 1

        Reject H0 (paired means equal) at confidence 1 − α when 0 is
        outside the CI mean(z) ± t_{α/2, n-1} · s_z / sqrt(n).

        First pass: per-test α = 1 − CL (each comparison stands alone).
        Second pass: Bonferroni-corrected per-test α = α_total / K with
        K = (#alternatives) × (#KPIs), so the family-wise confidence
        across all comparisons stays at 1 − α_total (Tutorial 10 slide 7,
        Tutorial 11 slide 14).
    """)

    print("\n  ===== Per-test α (no Bonferroni) =====")
    print_comparison(baseline_stats, combo_a_stats, combo_a_alt.name)
    print_comparison(baseline_stats, combo_b_stats, combo_b_alt.name)
    print_comparison(baseline_stats, combo_c_stats, combo_c_alt.name)

    # Bonferroni: K and alpha_bonf were already computed in Step 1.7.
    print("\n  ===== Bonferroni-corrected (K={}, α_per_test={:.4f}) =====".format(
        K, alpha_bonf))
    print_comparison(baseline_stats, combo_a_stats, combo_a_alt.name,
                     alpha_per_test=alpha_bonf)
    print_comparison(baseline_stats, combo_b_stats, combo_b_alt.name,
                     alpha_per_test=alpha_bonf)
    print_comparison(baseline_stats, combo_c_stats, combo_c_alt.name,
                     alpha_per_test=alpha_bonf)

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
