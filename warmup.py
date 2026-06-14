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
    
    def __init__(self, n_runs: int = 30):
        self.n_runs = n_runs

        samplers = fit_from_excel(_EXCEL_PATH)
        self._friends_sampler    = samplers.get('friends_interarrival')
        self._main_stage_sampler = samplers.get('main_stage_duration')
        self._cfg = build_baseline().config

        self.daily_avg_queue_lengths: List[float] = []
        self.daily_avg_satisfactions: List[float] = []

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
            if (i + 1) % 10 == 0:
                print("  Completed {}/{}".format(i + 1, self.n_runs))
        print("[Warm-Up Analysis] Done.\n")

    def plot_heating_time_data(self, data: List[float], label: str) -> None:
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
