"""
run_warmup_plots.py
===================
Run the Queuechella warm-up (heating-time) analysis and save/show all plots.

Usage:
    python run_warmup_plots.py              # 30 replications (default)
    python run_warmup_plots.py --runs 50   # custom count
    python run_warmup_plots.py --no-show   # save to plots/ without displaying
"""

import argparse

from warmup import WarmupSimulation
from plotting import plot_heating_time_data

# ── KPI definitions ──────────────────────────────────────────────────────────
# Each tuple: (attribute on WarmupSimulation, y-axis label, warmup_cutoff or None)
KPIS = [
    ('daily_avg_queue_lengths', 'Average Queue Length (min)',  None),
    ('daily_avg_satisfactions', 'Average Satisfaction (0-10)', None),
    ('daily_total_revenues',    'Total Revenue (NIS)',          None),
]


def main():
    parser = argparse.ArgumentParser(description='Warm-up analysis plots')
    parser.add_argument('--runs',    type=int, default=30,
                        help='Number of independent replications (default: 30)')
    parser.add_argument('--no-show', action='store_true',
                        help='Save plots to plots/ without displaying them')
    args = parser.parse_args()

    show = not args.no_show

    # ── Run replications ─────────────────────────────────────────────────────
    sim = WarmupSimulation(n_runs=args.runs)
    sim.run()

    # ── Plot each KPI ────────────────────────────────────────────────────────
    for attr, label, cutoff in KPIS:
        data = getattr(sim, attr)
        plot_heating_time_data(
            data,
            label=label,
            warmup_cutoff=cutoff,
            show=show,
            save=True,
            output_dir='plots',
        )

    print("Done. Plots saved to plots/")


if __name__ == '__main__':
    main()
