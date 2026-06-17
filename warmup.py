"""
warmup.py
=========
Warm-up (heating-time) period analysis for the Queuechella simulation.

Usage — identical pattern to the example hotel-simulation project:

    from warmup import WarmupSimulation

    sim = WarmupSimulation(30)
    sim.run()

    sim.plot_heating_time_data(sim.daily_avg_queue_lengths, 'Average Queue Length')
    sim.plot_heating_time_data(sim.daily_avg_satisfactions, 'Average Satisfaction')
"""

from __future__ import annotations

from typing import Callable, List, Optional

import matplotlib.pyplot as plt

import math

from alternatives import build_baseline
from distributions import (load_sample_data, fit_exponential, fit_normal,
                           fit_uniform, kolmogorov_smirnov_statistic,
                           sample_exponential, sample_normal,
                           sample_continuous_uniform)
from engine import Simulation as _Simulation
from sim_stats import MultiRunStatistics

import os

_EXCEL_PATH = os.path.join(os.path.dirname(__file__), 'samples_for_simulation.xlsx')


def _best_fit(data):
    """Fit Exp/Normal/Uniform to data and return a sampler for the best fit (lowest KS)."""
    mean_exp = fit_exponential(data)
    mu, sigma = fit_normal(data)
    a, b = fit_uniform(data)

    def exp_cdf(x):
        return 0.0 if x < 0 else 1.0 - math.exp(-x / mean_exp)

    def norm_cdf(x):
        return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    def unif_cdf(x):
        if x <= a: return 0.0
        if x >= b: return 1.0
        return (x - a) / (b - a)

    candidates = [
        ('Exponential', kolmogorov_smirnov_statistic(data, exp_cdf),
         lambda: sample_exponential(mean_exp)),
        ('Normal',      kolmogorov_smirnov_statistic(data, norm_cdf),
         lambda mu=mu, sigma=sigma: sample_normal(mu, sigma)),
        ('Uniform',     kolmogorov_smirnov_statistic(data, unif_cdf),
         lambda a=a, b=b: sample_continuous_uniform(a, b)),
    ]
    best = min(candidates, key=lambda c: c[1])
    print(f"  Best fit: {best[0]} (KS={best[1]:.4f})")
    return best[2]


def _fit_from_excel(xlsx_path):
    """Load Excel data and return fitted samplers for both columns."""
    sheets = load_sample_data(xlsx_path)
    keys   = list(sheets.keys())
    result = {}
    if len(keys) >= 1:
        print("[Fitting] FriendsGroup inter-arrival times:")
        result['friends_interarrival'] = _best_fit(sheets[keys[0]])
    if len(keys) >= 2:
        print("[Fitting] MainStage show duration:")
        result['main_stage_duration'] = _best_fit(sheets[keys[1]])
    return result


class WarmupSimulation:
    """
    Mirrors the interface of the example hotel-simulation project:

        sim = WarmupSimulation(30)
        sim.run()
        sim.plot_heating_time_data(sim.daily_avg_queue_lengths, 'Average Queue Length')
        sim.plot_heating_time_data(sim.daily_avg_satisfactions, 'Average Satisfaction')
    """

    def __init__(self, n_runs: int = 30):
        self.n_runs = n_runs

        samplers = _fit_from_excel(_EXCEL_PATH)
        self._friends_sampler    = samplers.get('friends_interarrival')
        self._main_stage_sampler = samplers.get('main_stage_duration')
        self._cfg = build_baseline().config

        self.daily_avg_queue_lengths: List[float] = []
        self.daily_avg_satisfactions: List[float] = []
        self.daily_total_revenues:    List[float] = []

    def run(self) -> None:
        """Run n_runs independent replications and store per-run KPIs."""
        print("\n[Warm-Up Analysis] Running {} replications...".format(self.n_runs))
        for i in range(self.n_runs):
            sim = _Simulation(
                self._cfg,
                friends_arrival_sampler=self._friends_sampler,
                main_stage_duration_sampler=self._main_stage_sampler,
            )
            stats = sim.run(seed=i)
            self.daily_avg_queue_lengths.append(stats.avg_queue_length)
            self.daily_avg_satisfactions.append(stats.avg_satisfaction)
            self.daily_total_revenues.append(stats.total_revenue)
            if (i + 1) % 10 == 0:
                print("  Completed {}/{}".format(i + 1, self.n_runs))
        print("[Warm-Up Analysis] Done.\n")

    def plot_heating_time_data(self, data: List[float], label: str) -> None:
        """
        Plot a per-replication KPI series with Welch's moving-average
        smoother overlaid — the standard heating-time plot.
        """
        smoothed = MultiRunStatistics.welch_moving_average(data)
        days = list(range(1, len(data) + 1))

        plt.figure(figsize=(10, 5))
        plt.plot(days, data, color='blue', linewidth=1.5, label='Original Data')
        plt.plot(days, smoothed, color='green', linewidth=1.5,
                 linestyle='--', label='Welsh Averages (Adjusted at End)')
        plt.xlabel('Days')
        plt.ylabel('Value')
        plt.title('Heating Time For ' + label)
        plt.legend()
        plt.tight_layout()
        plt.show()
