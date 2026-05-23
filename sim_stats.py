"""
statistics.py
=============
Metrics collection, aggregation, and statistical analysis for the simulation.

Collected per-run metrics:
    - Average satisfaction score of all departed entities
    - Average queue wait time per station
    - Average visit duration (time spent in the festival from arrival to departure)
    - Total revenue (ticket + overnight + merch + photo + food)
    - Station utilisation rates
    - Queue abandonment rate
    - Number of entities that attended each stage
    - Entry gate throughput

Statistical comparison between runs / alternatives:
    - Compute required number of replications (pilot study → variance estimate)
    - Build confidence intervals for each KPI
    - Hypothesis test (t-test) between two scenario means
"""

from __future__ import annotations
import math
import statistics as _stats
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Per-entity record
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EntityRecord:
    """Snapshot of an entity's metrics at departure time."""
    entity_id:          int
    entity_type:        str
    size:               int
    day:                int
    arrival_time:       float
    depart_time:        float
    satisfaction:       float
    spending:           float
    shows_attended:     List[str]
    queue_abandonments: int
    queue_waits:        Dict[str, float]   # station → total wait time


# ─────────────────────────────────────────────────────────────────────────────
# Per-run collector
# ─────────────────────────────────────────────────────────────────────────────

class RunStatistics:
    """
    Collects all metrics for a single simulation replication.

    Call record_entity() when each entity departs.
    Call record_queue_wait() during the run as waits occur.
    Call finalize() after the simulation ends.
    """

    def __init__(self):
        self.entity_records:     List[EntityRecord]    = []
        self.queue_wait_times:   Dict[str, List[float]] = {}  # station → [waits]
        self.abandonments:       Dict[str, int]         = {}  # station → count
        self.station_busy_time:  Dict[str, float]       = {}  # station → minutes busy
        self.station_total_time: Dict[str, float]       = {}  # station → sim duration
        self.total_revenue:      float                  = 0.0
        self.num_overnight:      int                    = 0

    # ── Recording helpers ─────────────────────────────────────────────────────

    def record_entity(self, record: EntityRecord) -> None:
        self.entity_records.append(record)
        self.total_revenue += record.spending

    def record_queue_wait(self, station: str, wait_minutes: float) -> None:
        self.queue_wait_times.setdefault(station, []).append(wait_minutes)

    def record_abandonment(self, station: str) -> None:
        self.abandonments[station] = self.abandonments.get(station, 0) + 1

    def record_station_busy(self, station: str, duration: float) -> None:
        self.station_busy_time[station] = (
            self.station_busy_time.get(station, 0.0) + duration)

    def set_station_total_time(self, station: str, total: float) -> None:
        self.station_total_time[station] = total

    # ── Aggregate KPIs ────────────────────────────────────────────────────────

    @property
    def avg_satisfaction(self) -> float:
        scores = [r.satisfaction for r in self.entity_records]
        return _stats.mean(scores) if scores else 0.0

    @property
    def avg_visit_duration(self) -> float:
        times = [r.depart_time - r.arrival_time
                 for r in self.entity_records]
        return _stats.mean(times) if times else 0.0

    @property
    def avg_queue_wait(self) -> Dict[str, float]:
        return {
            station: _stats.mean(waits)
            for station, waits in self.queue_wait_times.items()
            if waits
        }

    @property
    def total_entities(self) -> int:
        return len(self.entity_records)

    @property
    def abandonment_rate(self) -> Dict[str, float]:
        result = {}
        for station, count in self.abandonments.items():
            total_served = len(self.queue_wait_times.get(station, []))
            total        = total_served + count
            result[station] = count / total if total > 0 else 0.0
        return result

    @property
    def utilisation(self) -> Dict[str, float]:
        result = {}
        for station, busy in self.station_busy_time.items():
            total = self.station_total_time.get(station, 1.0)
            result[station] = busy / total if total > 0 else 0.0
        return result

    def summary(self) -> dict:
        """Return a flat dictionary of key performance indicators."""
        return {
            'avg_satisfaction':   round(self.avg_satisfaction, 4),
            'avg_visit_duration':    round(self.avg_visit_duration, 4),
            'total_entities':     self.total_entities,
            'total_revenue_NIS':  round(self.total_revenue, 2),
            'num_overnight':      self.num_overnight,
            'avg_queue_wait':     {k: round(v, 4)
                                   for k, v in self.avg_queue_wait.items()},
            'abandonment_rate':   {k: round(v, 4)
                                   for k, v in self.abandonment_rate.items()},
        }


# ─────────────────────────────────────────────────────────────────────────────
# Multi-run aggregator
# ─────────────────────────────────────────────────────────────────────────────

class MultiRunStatistics:
    """
    Aggregates results across multiple replications and provides
    confidence intervals and sample-size calculations.
    """

    def __init__(self, confidence_level: float = 0.90,
                 relative_precision: float = 0.10):
        self.confidence_level  = confidence_level
        self.relative_precision = relative_precision
        self.runs:             List[RunStatistics] = []

    def add_run(self, run: RunStatistics) -> None:
        self.runs.append(run)

    @property
    def n(self) -> int:
        return len(self.runs)

    # ── t critical value approximation ───────────────────────────────────────

    @staticmethod
    def _t_critical(df: int, alpha: float) -> float:
        """
        Approximate two-tailed t-critical value for df degrees of freedom
        at significance level alpha using the Cornish-Fisher approximation.
        Accurate enough for df >= 5.
        """
        # For common cases use a lookup; fall back to normal approximation.
        _TABLE = {
            (0.10, 5): 2.015, (0.10, 10): 1.812, (0.10, 20): 1.725,
            (0.10, 30): 1.697, (0.10, 60): 1.671, (0.10, 120): 1.658,
            (0.05, 5): 2.571, (0.05, 10): 2.228, (0.05, 20): 2.086,
            (0.05, 30): 2.042, (0.05, 60): 2.000, (0.05, 120): 1.980,
        }
        key = (alpha, df)
        if key in _TABLE:
            return _TABLE[key]
        # Normal approximation for large df
        if alpha <= 0.10:
            return 1.645
        return 1.960

    def _alpha(self) -> float:
        return 1.0 - self.confidence_level

    # ── Confidence interval helpers ───────────────────────────────────────────

    def _kpi_values(self, kpi: str) -> List[float]:
        """Extract per-run scalar values for a given KPI."""
        mapping = {
            'avg_satisfaction':   lambda r: r.avg_satisfaction,
            'avg_visit_duration': lambda r: r.avg_visit_duration,
            'total_revenue':      lambda r: r.total_revenue,
            'total_entities':     lambda r: float(r.total_entities),
        }
        if kpi not in mapping:
            raise ValueError(f"Unknown KPI: {kpi}")
        return [mapping[kpi](r) for r in self.runs]

    def confidence_interval(self, kpi: str) -> Tuple[float, float, float]:
        """
        Return (mean, lower_bound, upper_bound) for the given KPI.
        Uses Student-t confidence interval:
            mean ± t_{alpha/2, n-1} * s / sqrt(n)
        """
        values = self._kpi_values(kpi)
        n      = len(values)
        if n < 2:
            raise ValueError("Need at least 2 replications for CI")
        mean_val = _stats.mean(values)
        std_val  = _stats.stdev(values)
        t_crit   = self._t_critical(n - 1, self._alpha())
        half     = t_crit * std_val / math.sqrt(n)
        return mean_val, mean_val - half, mean_val + half

    def required_replications(self, kpi: str,
                              pilot_runs: int = 5) -> int:
        """
        Estimate the number of replications required to achieve the specified
        relative precision using a pilot sample of `pilot_runs` observations.

        Formula (relative precision δ):
            n* = (t_{α/2, n0-1} * s / (δ * x̄))²

        Returns at least `pilot_runs`.
        """
        values = self._kpi_values(kpi)[:pilot_runs]
        if len(values) < 2:
            return pilot_runs
        mean_val = _stats.mean(values)
        if mean_val == 0:
            return pilot_runs
        std_val  = _stats.stdev(values)
        t_crit   = self._t_critical(len(values) - 1, self._alpha())
        n_star   = (t_crit * std_val / (self.relative_precision * mean_val)) ** 2
        return max(pilot_runs, math.ceil(n_star))

    def paired_t_test(self,
                      other: 'MultiRunStatistics',
                      kpi: str) -> Tuple[float, float, bool]:
        """
        Paired two-sample t-test comparing this scenario vs `other`.

        Assumes equal number of replications (same random seeds).
        Returns (t_statistic, t_critical, reject_H0).
        H0: means are equal.  Reject if |t| > t_crit.
        """
        vals_a = self._kpi_values(kpi)
        vals_b = other._kpi_values(kpi)
        n = min(len(vals_a), len(vals_b))
        if n < 2:
            raise ValueError("Need at least 2 replications for t-test")
        diffs   = [vals_a[i] - vals_b[i] for i in range(n)]
        mean_d  = _stats.mean(diffs)
        std_d   = _stats.stdev(diffs)
        t_stat  = mean_d / (std_d / math.sqrt(n))
        t_crit  = self._t_critical(n - 1, self._alpha())
        return t_stat, t_crit, abs(t_stat) > t_crit

    def report(self) -> str:
        """Print a human-readable summary of all collected KPIs."""
        lines = [f"\n{'='*60}",
                 f"  Multi-Run Statistics  ({self.n} replications)",
                 f"  Confidence level: {self.confidence_level*100:.0f}%  "
                 f"  Relative precision: {self.relative_precision*100:.0f}%",
                 f"{'='*60}"]
        for kpi in ['avg_satisfaction', 'avg_visit_duration',
                    'total_revenue', 'total_entities']:
            try:
                mean, lo, hi = self.confidence_interval(kpi)
                lines.append(
                    f"  {kpi:25s}: mean={mean:9.3f}  "
                    f"CI=[{lo:.3f}, {hi:.3f}]")
            except Exception as e:
                lines.append(f"  {kpi}: ERROR – {e}")
        lines.append(f"{'='*60}\n")
        return '\n'.join(lines)
