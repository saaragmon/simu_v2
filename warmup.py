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
    sim.plot_heating_time_data(sim.daily_total_revenues, 'Total Revenue')
"""

from __future__ import annotations

from typing import Callable, List, Optional

import matplotlib.pyplot as plt

from alternatives import build_baseline
from distributions import fit_from_excel
from engine import Simulation as _Simulation
from sim_stats import MultiRunStatistics

import os

_EXCEL_PATH = os.path.join(os.path.dirname(__file__), 'samples_for_simulation.xlsx')


class WarmupSimulation:
    """
    Mirrors the interface of the example hotel-simulation project:

        sim = WarmupSimulation(30)
        sim.run()
        sim.plot_heating_time_data(sim.daily_avg_queue_lengths, 'Average Queue Length')
        sim.plot_heating_time_data(sim.daily_avg_satisfactions, 'Average Satisfaction')
        sim.plot_heating_time_data(sim.daily_total_revenues, 'Total Revenue')
    """

    def __init__(self, n_runs: int = 30, cfg=None):
        self.n_runs = n_runs

        samplers = fit_from_excel(_EXCEL_PATH)
        self._friends_sampler    = samplers.get('friends_interarrival')
        self._main_stage_sampler = samplers.get('main_stage_duration')
        self._cfg = cfg if cfg is not None else build_baseline().config

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
