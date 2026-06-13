"""
warmup.py
=========
Warm-up (heating-time) period analysis for the Queuechella simulation.

For a finite-horizon festival that always starts empty, we check
whether the per-replication KPIs stabilise quickly or show early-run
transient behaviour.  We run N replications, collect two key KPIs per
run, and plot them with Welch's moving-average smoother so the warm-up
period can be identified visually.

Usage (main.py or Colab):
    from warmup import run_warmup_analysis
    from plotting import plot_heating_time_data

    series = run_warmup_analysis(cfg, n_runs=30,
                                 friends_sampler=friends_sampler,
                                 main_stage_sampler=main_stage_sampler)
    plot_heating_time_data(series['avg_queue_length'],
                           'Average Queue Length', warmup_cutoff=5)
    plot_heating_time_data(series['avg_satisfaction'],
                           'Average Satisfaction',  warmup_cutoff=5)
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from engine import Simulation


# KPIs collected across replications for the warm-up plots
WARMUP_KPIS = ['avg_queue_length', 'avg_satisfaction',
               'total_revenue', 'total_entities']


def run_warmup_analysis(
    cfg,
    n_runs: int = 30,
    friends_sampler: Optional[Callable] = None,
    main_stage_sampler: Optional[Callable] = None,
) -> Dict[str, List[float]]:
    """
    Run n_runs independent replications and return a dict of per-run
    KPI series ready for heating-time plots.

    Args:
        cfg:                SimConfig for the scenario (use Baseline).
        n_runs:             Number of replications to run (default 30).
        friends_sampler:    Fitted FriendsGroup inter-arrival sampler.
        main_stage_sampler: Fitted MainStage duration sampler.

    Returns:
        Dict mapping KPI name -> list of n_runs float values.
        Keys: 'avg_queue_length', 'avg_satisfaction',
              'total_revenue', 'total_entities'.
    """
    series: Dict[str, List[float]] = {kpi: [] for kpi in WARMUP_KPIS}

    print("\n[Warm-Up Analysis] Running {} replications...".format(n_runs))
    for i in range(n_runs):
        sim = Simulation(
            cfg,
            friends_arrival_sampler=friends_sampler,
            main_stage_duration_sampler=main_stage_sampler,
        )
        stats = sim.run(seed=i)
        series['avg_queue_length'].append(stats.avg_queue_length)
        series['avg_satisfaction'].append(stats.avg_satisfaction)
        series['total_revenue'].append(stats.total_revenue)
        series['total_entities'].append(float(stats.total_entities))
        if (i + 1) % 10 == 0:
            print("  Completed {}/{}".format(i + 1, n_runs))

    print("[Warm-Up Analysis] Done.\n")
    return series
