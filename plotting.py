"""
plotting.py
===========
Visualizations for a single Queuechella simulation run.

    - "Plots for Heating Time" — time-series of system load and revenue
      over the festival hours.
    - "Data Points For Current State" — distributions of final
      satisfaction, visit duration, and per-station queue waits.

Usage:
    from engine import Simulation
    from alternatives import build_baseline
    from plotting import RunPlotter

    sim   = Simulation(build_baseline().config)
    stats = sim.run(seed=42)

    plotter = RunPlotter(stats, name='Baseline')
    plotter.plot_all()                       # show all plots
    plotter.plot_all(save=True, show=False)  # save to plots/ only
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Dict, List, Optional

import matplotlib.pyplot as plt

from config import FESTIVAL_START, DAY_DURATION
from sim_stats import MultiRunStatistics


# ─── Visual style (matches the hotel example + plot_distributions.py) ────────
UNIFIED_BLUE = "#80CEED"
UNIFIED_PINK = "#FCB8D6"
UNIFIED_GREEN = "#9BD49E"
TEXT_COLOR   = "dimgray"
ENTITY_COLORS = {
    'FriendsGroup': "#80CEED",
    'Couple':       "#FCB8D6",
    'Single':       "#9BD49E",
}


def _minute_to_label(t: float) -> str:
    """Convert minutes-from-midnight-of-day-1 to a day+hour label like 'D1 12:00'."""
    day = 1 if t < FESTIVAL_START + DAY_DURATION else 2
    minute_in_day = t - FESTIVAL_START - (day - 1) * DAY_DURATION
    hour = int(FESTIVAL_START / 60 + minute_in_day / 60)
    return "D{} {:02d}:00".format(day, hour % 24)


class RunPlotter:
    """Generates visualizations for one simulation run.

    Args:
        stats:      a RunStatistics object (filled in by `Simulation.run`).
        name:       label used in figure titles and saved filenames.
        output_dir: where to save PNGs when `save=True`.
    """

    def __init__(self, stats, name: str = 'Run', output_dir: str = 'plots'):
        self.stats = stats
        self.name = name
        self.output_dir = output_dir

    # ─────────────────────────────────────────────────────────────────────────
    # Time-series plots  (analogous to "Plots for Heating Time")
    # ─────────────────────────────────────────────────────────────────────────

    def plot_concurrent_entities(self, ax=None):
        """Number of entities inside the festival at each minute."""
        records = self.stats.entity_records
        if not records:
            return None

        t_start = FESTIVAL_START
        t_end   = FESTIVAL_START + 2 * DAY_DURATION
        timeline = list(range(int(t_start), int(t_end) + 1, 5))   # every 5 min
        counts = []
        for t in timeline:
            counts.append(sum(1 for r in records
                              if r.arrival_time <= t < r.depart_time))

        if ax is None:
            fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(timeline, counts, color=UNIFIED_BLUE, linewidth=2)
        ax.fill_between(timeline, counts, color=UNIFIED_BLUE, alpha=0.3)
        ax.axvline(FESTIVAL_START + DAY_DURATION, color='gray',
                   linestyle='--', alpha=0.6, label='End of Day 1')
        ax.set_xlabel('Time (minutes from midnight Day 1)', color=TEXT_COLOR)
        ax.set_ylabel('Entities currently inside', color=TEXT_COLOR)
        ax.set_title('Concurrent Entities Over Time — ' + self.name,
                     color=TEXT_COLOR)
        ax.grid(True, alpha=0.3)
        ax.legend()
        return ax

    def plot_cumulative_revenue(self, ax=None):
        """Cumulative revenue over the festival (one step per departing entity)."""
        records = sorted(self.stats.entity_records, key=lambda r: r.depart_time)
        if not records:
            return None

        times = [r.depart_time for r in records]
        cumulative = []
        running = 0.0
        for r in records:
            running += r.spending
            cumulative.append(running)

        if ax is None:
            fig, ax = plt.subplots(figsize=(11, 5))
        ax.step(times, cumulative, where='post',
                color=UNIFIED_PINK, linewidth=2)
        ax.axvline(FESTIVAL_START + DAY_DURATION, color='gray',
                   linestyle='--', alpha=0.6, label='End of Day 1')
        ax.set_xlabel('Time (minutes from midnight Day 1)', color=TEXT_COLOR)
        ax.set_ylabel('Cumulative revenue (NIS)', color=TEXT_COLOR)
        ax.set_title('Cumulative Revenue Over Time — ' + self.name,
                     color=TEXT_COLOR)
        ax.grid(True, alpha=0.3)
        ax.legend()
        return ax

    def plot_arrivals_per_hour(self, ax=None):
        """Bar chart of entity arrivals per hour, stacked by entity type."""
        records = self.stats.entity_records
        if not records:
            return None

        buckets: Dict[int, Counter] = {}
        for r in records:
            hour = int(r.arrival_time // 60)
            buckets.setdefault(hour, Counter())[r.entity_type] += 1

        hours = sorted(buckets.keys())
        types = ['FriendsGroup', 'Couple', 'Single']

        if ax is None:
            fig, ax = plt.subplots(figsize=(11, 5))
        bottom = [0] * len(hours)
        for t in types:
            counts = [buckets[h].get(t, 0) for h in hours]
            ax.bar(hours, counts, bottom=bottom,
                   color=ENTITY_COLORS[t], label=t, edgecolor='white')
            bottom = [b + c for b, c in zip(bottom, counts)]

        ax.set_xlabel('Hour of day (from midnight)', color=TEXT_COLOR)
        ax.set_ylabel('Arrivals', color=TEXT_COLOR)
        ax.set_title('Arrivals per Hour — ' + self.name, color=TEXT_COLOR)
        ax.grid(True, axis='y', alpha=0.3)
        ax.legend()
        return ax

    # ─────────────────────────────────────────────────────────────────────────
    # Distribution plots  ("Data Points For Current State")
    # ─────────────────────────────────────────────────────────────────────────

    def plot_satisfaction_histogram(self, ax=None):
        """Histogram of final satisfaction scores, coloured by entity type."""
        records = self.stats.entity_records
        if not records:
            return None

        by_type: Dict[str, List[float]] = {}
        for r in records:
            by_type.setdefault(r.entity_type, []).append(r.satisfaction)

        if ax is None:
            fig, ax = plt.subplots(figsize=(10, 5))
        for t, scores in by_type.items():
            ax.hist(scores, bins=20, alpha=0.6, label=t,
                    color=ENTITY_COLORS.get(t, UNIFIED_BLUE),
                    edgecolor='black')
        mean = sum(r.satisfaction for r in records) / len(records)
        ax.axvline(mean, color='red', linestyle='--',
                   label='Mean = {:.2f}'.format(mean))
        ax.set_xlabel('Satisfaction score (0-10)', color=TEXT_COLOR)
        ax.set_ylabel('Number of entities', color=TEXT_COLOR)
        ax.set_title('Final Satisfaction Distribution — ' + self.name,
                     color=TEXT_COLOR)
        ax.grid(True, alpha=0.3)
        ax.legend()
        return ax

    # ─────────────────────────────────────────────────────────────────────────
    # Per-station bar charts
    # ─────────────────────────────────────────────────────────────────────────

    def plot_queue_waits(self, ax=None):
        """Average queue wait per station (lower is better)."""
        waits = self.stats.avg_queue_wait
        if not waits:
            return None

        stations = list(waits.keys())
        values   = [waits[s] for s in stations]

        if ax is None:
            fig, ax = plt.subplots(figsize=(10, 5))
        ax.barh(stations, values, color=UNIFIED_BLUE, edgecolor='black')
        for i, v in enumerate(values):
            ax.text(v, i, ' {:.1f}'.format(v), va='center',
                    color=TEXT_COLOR)
        ax.set_xlabel('Average wait (minutes)', color=TEXT_COLOR)
        ax.set_title('Average Queue Wait by Station — ' + self.name,
                     color=TEXT_COLOR)
        ax.grid(True, axis='x', alpha=0.3)
        return ax

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience: all plots at once
    # ─────────────────────────────────────────────────────────────────────────

    def plot_all(self, show: bool = True, save: bool = True):
        """Generate every plot in a single 4×2 dashboard figure."""
        fig, axes = plt.subplots(4, 2, figsize=(18, 22))

        self.plot_concurrent_entities(ax=axes[0, 0])
        self.plot_cumulative_revenue(ax=axes[0, 1])
        self.plot_arrivals_per_hour(ax=axes[1, 0])
        self.plot_satisfaction_histogram(ax=axes[1, 1])
        self.plot_queue_waits(ax=axes[2, 0])
        axes[2, 1].axis('off')
        axes[3, 0].axis('off')
        axes[3, 1].axis('off')

        fig.suptitle('Simulation Dashboard — ' + self.name,
                     fontsize=16, color=TEXT_COLOR, y=0.995)
        fig.tight_layout(rect=[0, 0, 1, 0.99])

        if save:
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir,
                                'dashboard_' + self.name + '.png')
            fig.savefig(path, dpi=120, bbox_inches='tight')
            print('  Saved dashboard to: {}'.format(path))
        if show:
            plt.show()
        else:
            plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Cross-scenario KPI comparisons
# ─────────────────────────────────────────────────────────────────────────────

SCENARIO_COLORS = [UNIFIED_BLUE, UNIFIED_PINK, UNIFIED_GREEN,
                   "#FFD580", "#C8A2C8"]


class KPIComparisonPlotter:
    """Compare multiple scenarios across each KPI.

    Takes a dict ``{scenario_name: MultiRunStatistics}`` and draws:
        - bar chart of the mean per scenario with t-based CI error bars,
        - box plot of the per-run KPI values across replications,
    for every KPI it is asked about.

    Args:
        scenarios:        dict mapping scenario name to MultiRunStatistics.
        kpi_higher_better: dict ``{kpi_name: bool}`` — used to annotate
                          the "↑ better / ↓ better" direction on each axis.
        output_dir:       where to save PNGs.
    """

    def __init__(self,
                 scenarios: Dict[str, 'MultiRunStatistics'],
                 kpi_higher_better: Optional[Dict[str, bool]] = None,
                 output_dir: str = 'plots'):
        self.scenarios = scenarios
        self.kpi_higher_better = kpi_higher_better or {}
        self.output_dir = output_dir

    # ─────────────────────────────────────────────────────────────────────────

    def _direction(self, kpi: str) -> str:
        if kpi not in self.kpi_higher_better:
            return ''
        return '(higher better)' if self.kpi_higher_better[kpi] \
                                 else '(lower better)'

    def plot_kpi_bars_with_ci(self, kpi: str, ax=None):
        """Bar chart of mean(KPI) per scenario with confidence-interval error bars."""
        names = list(self.scenarios.keys())
        means, lows, highs = [], [], []
        for n in names:
            m, lo, hi = self.scenarios[n].confidence_interval(kpi)
            means.append(m)
            lows.append(m - lo)   # half-widths for error bars
            highs.append(hi - m)

        if ax is None:
            fig, ax = plt.subplots(figsize=(8, 5))

        colors = [SCENARIO_COLORS[i % len(SCENARIO_COLORS)]
                  for i in range(len(names))]
        ax.bar(names, means, color=colors, edgecolor='black',
               yerr=[lows, highs], capsize=8, ecolor=TEXT_COLOR)
        for i, m in enumerate(means):
            ax.text(i, m, ' {:.2f}'.format(m), ha='center',
                    va='bottom', color=TEXT_COLOR)
        ax.set_ylabel(kpi, color=TEXT_COLOR)
        ax.set_title('{} {} — Mean ± CI'.format(kpi, self._direction(kpi)),
                     color=TEXT_COLOR)
        ax.grid(True, axis='y', alpha=0.3)
        return ax

    def plot_kpi_boxplot(self, kpi: str, ax=None):
        """Box plot of per-run KPI values across replications, one box per scenario."""
        names = list(self.scenarios.keys())
        data  = [self.scenarios[n]._kpi_values(kpi) for n in names]

        if ax is None:
            fig, ax = plt.subplots(figsize=(8, 5))

        bp = ax.boxplot(data, labels=names, patch_artist=True,
                        widths=0.55)
        for i, patch in enumerate(bp['boxes']):
            patch.set_facecolor(SCENARIO_COLORS[i % len(SCENARIO_COLORS)])
            patch.set_edgecolor('black')
        for median in bp['medians']:
            median.set_color('red')
            median.set_linewidth(2)
        ax.set_ylabel(kpi, color=TEXT_COLOR)
        ax.set_title('{} {} — Per-Run Distribution'.format(
            kpi, self._direction(kpi)), color=TEXT_COLOR)
        ax.grid(True, axis='y', alpha=0.3)
        return ax

    # ─────────────────────────────────────────────────────────────────────────

    def plot_all_kpis(self, kpis: List[str],
                      show: bool = True, save: bool = True,
                      filename: str = 'kpi_comparison.png'):
        """Two-column grid (bars | boxplots), one row per KPI."""
        rows = len(kpis)
        fig, axes = plt.subplots(rows, 2, figsize=(15, 4 * rows))
        if rows == 1:
            axes = [axes]   # normalise to 2D-ish indexing

        for r, kpi in enumerate(kpis):
            self.plot_kpi_bars_with_ci(kpi, ax=axes[r][0])
            self.plot_kpi_boxplot      (kpi, ax=axes[r][1])

        scenario_label = ' vs '.join(self.scenarios.keys())
        fig.suptitle('KPI Comparison — ' + scenario_label,
                     fontsize=16, color=TEXT_COLOR, y=0.995)
        fig.tight_layout(rect=[0, 0, 1, 0.985])

        if save:
            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, filename)
            fig.savefig(path, dpi=120, bbox_inches='tight')
            print('  Saved KPI comparison to: {}'.format(path))
        if show:
            plt.show()
        else:
            plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: plot directly from main.py
# ─────────────────────────────────────────────────────────────────────────────

def plot_run(stats, name='Run', show=True, save=True, output_dir='plots'):
    """Build a RunPlotter and emit the dashboard. One-liner for main.py."""
    plotter = RunPlotter(stats, name=name, output_dir=output_dir)
    plotter.plot_all(show=show, save=save)


# ─────────────────────────────────────────────────────────────────────────────
# Warm-up (heating-time) plot
# ─────────────────────────────────────────────────────────────────────────────

def plot_heating_time_data(
    data: List[float],
    label: str,
    warmup_cutoff: Optional[int] = None,
    show: bool = True,
    save: bool = True,
    output_dir: str = 'plots',
) -> None:
    """
    Plot a per-replication KPI series with Welch's moving-average
    smoother overlaid — the standard heating-time (warm-up) plot.

    Args:
        data:           list of per-replication KPI values.
        label:          y-axis label and figure title.
        warmup_cutoff:  if given, draws a vertical dashed line at this
                        replication number to mark the chosen warm-up end.
        show / save:    display or write PNG to output_dir.
    """
    smoothed = MultiRunStatistics.welch_moving_average(data)
    reps = list(range(1, len(data) + 1))

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(reps, data, color=UNIFIED_BLUE, linewidth=1.2,
            alpha=0.7, label='Per-replication value')
    ax.plot(reps, smoothed, color='red', linewidth=2.0,
            label="Welch's moving average")
    if warmup_cutoff is not None:
        ax.axvline(warmup_cutoff, color='orange', linestyle='--',
                   linewidth=1.8,
                   label='Warm-up cutoff (rep {})'.format(warmup_cutoff))
    ax.set_xlabel('Replication number', color=TEXT_COLOR)
    ax.set_ylabel(label, color=TEXT_COLOR)
    ax.set_title('Heating Time — ' + label, color=TEXT_COLOR)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    if save:
        os.makedirs(output_dir, exist_ok=True)
        safe = label.replace(' ', '_').replace('/', '_')
        path = os.path.join(output_dir, 'warmup_{}.png'.format(safe))
        fig.savefig(path, dpi=120, bbox_inches='tight')
        print('  Saved warm-up plot to: {}'.format(path))
    if show:
        plt.show()
    else:
        plt.close(fig)
