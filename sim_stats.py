"""
sim_stats.py
============
Metrics collection, aggregation, and statistical analysis for the simulation.

Collected per-run metrics:
    - Average satisfaction score of all departed entities      (KPI)
    - Average visit duration (depart_time - arrival_time)      (KPI)
    - Total revenue (ticket + overnight + merch + photo + food) (KPI)
    - Total number of departed entities                        (KPI)
    - Average queue wait per station
    - Queue abandonment rate per station
    - Station utilisation
    - Number of overnight stays

Statistical analysis across replications:
    - Welch's moving average (warm-up / heating-time identification)
    - Required number of replications (pilot study → variance estimate)
    - Student-t confidence intervals
    - Welch's two-sample t-test       (recommended; independent samples)
    - Paired t-test                   (only valid under Common Random Numbers)

Math reference
--------------
* Mean / std formulas use the unbiased sample variance (Bessel's correction).
* Student-t critical values come from scipy.stats.t (more accurate than a
  lookup table).
* Welch's t-test:
      t  = (x_bar1 - x_bar2) / sqrt(s1^2/n1 + s2^2/n2)
      df = (s1^2/n1 + s2^2/n2)^2 / ((s1^2/n1)^2/(n1-1) + (s2^2/n2)^2/(n2-1))
* Required replications (relative precision δ at confidence 1-α):
      n* = ceil( (t_{α/2, n0-1} * s / (δ * x_bar))^2 )
"""

from __future__ import annotations
import math
import statistics as _stats
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

try:
    from scipy.stats import t as student_t
except Exception:  # pragma: no cover - fall back when scipy is not installed
    class _MissingScipyT:
        def ppf(self, *args, **kwargs):
            raise RuntimeError(
                "scipy is required for statistical functions in sim_stats.py; "
                "please install scipy (pip install scipy)"
            )

        def cdf(self, *args, **kwargs):
            raise RuntimeError(
                "scipy is required for statistical functions in sim_stats.py; "
                "please install scipy (pip install scipy)"
            )

    student_t = _MissingScipyT()


# ─────────────────────────────────────────────────────────────────────────────
# Per-entity record
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EntityRecord:
    """Snapshot of one entity's metrics, captured at the moment of departure."""
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
    queue_waits:        Dict[str, float]


# ─────────────────────────────────────────────────────────────────────────────
# Per-run collector
# ─────────────────────────────────────────────────────────────────────────────

class RunStatistics:
    """
    Collects all metrics for a single simulation replication.

    The engine writes here as events occur:
        - record_entity()    when an entity departs
        - record_queue_wait() when service begins for a queued entity
        - record_abandonment() when an entity gives up waiting
    Read the aggregate KPIs via the @property accessors at the end of the run.
    """

    def __init__(self):
        self.entity_records:     List[EntityRecord]     = []
        self.queue_wait_times:   Dict[str, List[float]] = {}
        self.abandonments:       Dict[str, int]         = {}
        self.station_busy_time:  Dict[str, float]       = {}
        self.station_total_time: Dict[str, float]       = {}
        self.total_revenue:      float                  = 0.0
        self.num_overnight:      int                    = 0

    # ── Recording helpers ─────────────────────────────────────────────────────

    def record_entity(self, record):
        """Called by the engine when an entity departs the festival."""
        self.entity_records.append(record)
        self.total_revenue += record.spending

    def record_queue_wait(self, station, wait_minutes):
        """Record one waiting-time observation at the given station."""
        self.queue_wait_times.setdefault(station, []).append(wait_minutes)

    def record_abandonment(self, station):
        """Increment the abandonment counter for the given station."""
        self.abandonments[station] = self.abandonments.get(station, 0) + 1

    def record_station_busy(self, station, duration):
        self.station_busy_time[station] = (
            self.station_busy_time.get(station, 0.0) + duration)

    def set_station_total_time(self, station, total):
        self.station_total_time[station] = total

    # ── Aggregate KPIs ────────────────────────────────────────────────────────

    @property
    def avg_satisfaction(self):
        """Mean satisfaction across all departed entities; higher is better."""
        scores = [r.satisfaction for r in self.entity_records]
        if len(scores) > 0:
            return _stats.mean(scores)
        return 0.0

    @property
    def avg_visit_duration(self):
        """Mean time (minutes) an entity spent inside the festival.

        visit_duration = depart_time - arrival_time

        Lower is better — long visits usually mean entities got stuck in
        queues or had to wait for shows.
        """
        times = [r.depart_time - r.arrival_time
                 for r in self.entity_records]
        if len(times) > 0:
            return _stats.mean(times)
        return 0.0

    @property
    def avg_queue_wait(self):
        """Average wait time (min) per service station."""
        return {
            station: _stats.mean(waits)
            for station, waits in self.queue_wait_times.items()
            if waits
        }

    @property
    def total_entities(self):
        """Number of entities that completed the simulation."""
        return len(self.entity_records)

    @property
    def abandonment_rate(self):
        """Proportion of arrivals that abandoned each station's queue."""
        result = {}
        for station, count in self.abandonments.items():
            total_served = len(self.queue_wait_times.get(station, []))
            total = total_served + count
            if total > 0:
                result[station] = count / total
            else:
                result[station] = 0.0
        return result

    @property
    def utilisation(self):
        """Server-busy fraction per station (rough, only set if measured)."""
        result = {}
        for station, busy in self.station_busy_time.items():
            total = self.station_total_time.get(station, 1.0)
            if total > 0:
                result[station] = busy / total
            else:
                result[station] = 0.0
        return result

    def summary(self):
        """Return a flat dictionary of KPIs (convenient for printing)."""
        return {
            'avg_satisfaction':    round(self.avg_satisfaction, 4),
            'avg_visit_duration':  round(self.avg_visit_duration, 4),
            'total_entities':      self.total_entities,
            'total_revenue_NIS':   round(self.total_revenue, 2),
            'num_overnight':       self.num_overnight,
            'avg_queue_wait':      {k: round(v, 4)
                                    for k, v in self.avg_queue_wait.items()},
            'abandonment_rate':    {k: round(v, 4)
                                    for k, v in self.abandonment_rate.items()},
        }


# ─────────────────────────────────────────────────────────────────────────────
# Multi-run aggregator
# ─────────────────────────────────────────────────────────────────────────────

class MultiRunStatistics:
    """
    Aggregate results from N independent replications and run the
    standard suite of comparison tests.
    """

    def __init__(self, confidence_level=0.95, relative_precision=0.10):
        self.confidence_level = confidence_level
        self.relative_precision = relative_precision
        self.runs: List[RunStatistics] = []

    def add_run(self, run):
        self.runs.append(run)

    @property
    def n(self):
        return len(self.runs)

    def _alpha(self):
        """Significance level α = 1 - CL."""
        return 1.0 - self.confidence_level

    @staticmethod
    def _t_critical(df, alpha):
        """
        Two-tailed Student-t critical value at significance α with df
        degrees of freedom. Uses scipy for accuracy.

            t_{α/2, df}  such that  P(|T| > t_{α/2,df}) = α
        """
        return float(student_t.ppf(1.0 - alpha / 2.0, df))

    # ── KPI value extraction ─────────────────────────────────────────────────

    def _kpi_values(self, kpi):
        """Return the list of per-run KPI values."""
        mapping = {
            'avg_satisfaction':   lambda r: r.avg_satisfaction,
            'avg_visit_duration': lambda r: r.avg_visit_duration,
            'total_revenue':      lambda r: r.total_revenue,
            'total_entities':     lambda r: float(r.total_entities),
        }
        if kpi not in mapping:
            raise ValueError("Unknown KPI: " + kpi)
        return [mapping[kpi](r) for r in self.runs]

    # ── Confidence interval ─────────────────────────────────────────────────

    def confidence_interval(self, kpi):
        """
        Student-t (1 - α) confidence interval for the mean of the given KPI.

            CI = x_bar ± t_{α/2, n-1} * s / sqrt(n)

        Returns:
            (mean, lower_bound, upper_bound)
        """
        values = self._kpi_values(kpi)
        n = len(values)
        if n < 2:
            raise ValueError("Need at least 2 replications for CI")

        mean_val = _stats.mean(values)
        std_val = _stats.stdev(values)
        t_crit = self._t_critical(n - 1, self._alpha())
        half_width = t_crit * std_val / math.sqrt(n)

        return mean_val, mean_val - half_width, mean_val + half_width

    # ── Required replications (pilot-study formula) ─────────────────────────

    def required_replications(self, kpi, pilot_runs=5):
        """
        Estimate the number of replications required to achieve the
        configured relative precision δ at confidence level 1 - α.

        Formula (Banks et al., 'Discrete-Event System Simulation'):

            n* = ceil( (t_{α/2, n0-1} * s / (δ * x_bar))^2 )

        where n0 is the pilot-sample size, s is the sample std, x_bar the
        sample mean, and δ the desired relative precision.
        """
        values = self._kpi_values(kpi)[:pilot_runs]
        if len(values) < 2:
            return pilot_runs

        mean_val = _stats.mean(values)
        if mean_val == 0:
            return pilot_runs

        std_val = _stats.stdev(values)
        t_crit = self._t_critical(len(values) - 1, self._alpha())
        n_star = (t_crit * std_val / (self.relative_precision * mean_val)) ** 2
        return max(pilot_runs, math.ceil(n_star))

    # ── Welch's two-sample t-test (independent samples) ─────────────────────

    def welch_t_test(self, other, kpi):
        """
        Welch's two-sample t-test for two independent groups with unequal
        variances. This is the appropriate test when each replication uses
        an independent RNG seed (no CRN).

            t  = (x_bar1 - x_bar2) / sqrt(s1^2/n1 + s2^2/n2)
            df = (s1^2/n1 + s2^2/n2)^2
                 / ((s1^2/n1)^2 / (n1-1) + (s2^2/n2)^2 / (n2-1))

        H0: the two scenarios have equal means.
        Reject H0 (two-tailed) when |t| > t_{α/2, df}.

        Returns:
            (t_statistic, t_critical, reject_H0_boolean)
        """
        v1 = self._kpi_values(kpi)
        v2 = other._kpi_values(kpi)
        n1, n2 = len(v1), len(v2)
        if n1 < 2 or n2 < 2:
            raise ValueError("Need at least 2 replications in each group")

        m1, m2 = _stats.mean(v1), _stats.mean(v2)
        s1_sq = _stats.variance(v1)
        s2_sq = _stats.variance(v2)

        se = math.sqrt(s1_sq / n1 + s2_sq / n2)
        if se == 0:
            return 0.0, self._t_critical(n1 + n2 - 2, self._alpha()), False

        t_stat = (m1 - m2) / se

        # Welch–Satterthwaite degrees of freedom
        num = (s1_sq / n1 + s2_sq / n2) ** 2
        den = ((s1_sq / n1) ** 2) / (n1 - 1) + ((s2_sq / n2) ** 2) / (n2 - 1)
        df = num / den

        t_crit = self._t_critical(df, self._alpha())
        return t_stat, t_crit, abs(t_stat) > t_crit

    # ── Paired t-test (only valid with Common Random Numbers) ────────────────

    def paired_t_test(self, other, kpi):
        """
        Paired two-sample t-test. Valid only when run i of THIS scenario
        and run i of `other` used the same random-number stream (CRN).

        Under CRN the difference d_i = x_i - y_i has lower variance,
        giving a more powerful test. Without CRN, use welch_t_test instead.
        """
        v1 = self._kpi_values(kpi)
        v2 = other._kpi_values(kpi)
        n = min(len(v1), len(v2))
        if n < 2:
            raise ValueError("Need at least 2 paired replications")

        diffs = [v1[i] - v2[i] for i in range(n)]
        mean_d = _stats.mean(diffs)
        std_d = _stats.stdev(diffs)
        t_stat = mean_d / (std_d / math.sqrt(n))
        t_crit = self._t_critical(n - 1, self._alpha())
        return t_stat, t_crit, abs(t_stat) > t_crit

    # ── Heating-time (Welch's moving average) ───────────────────────────────

    @staticmethod
    def welch_moving_average(data, window=9):
        """
        Welch's method for warm-up identification.

        For each point i in the time series, average the surrounding
        2w+1 points (truncating the window near the boundaries).
        Plotting the smoothed series visually reveals when the system
        reaches steady state.

        Algorithm:
            For i < w:           use points 0 .. 2i
            For w <= i < n-w:    use points i-w .. i+w
            For i >= n-w:        use points i-w .. n-1

        Args:
            data: a 1-D list of per-period observations (e.g., daily
                  average queue length).
            window: half-window size w (default 9, as in the hotel example).

        Returns:
            list of smoothed values, same length as `data`.
        """
        n = len(data)
        smoothed = []
        for i in range(n):
            if i < window:
                start = 0
                end = 2 * i + 1
            elif i < n - window:
                start = i - window
                end = i + window + 1
            else:
                start = max(0, i - window)
                end = n
            window_slice = data[start:end]
            smoothed.append(sum(window_slice) / len(window_slice))
        return smoothed

    # ── Human-readable report ──────────────────────────────────────────────

    def report(self):
        """
        Print a textual summary of all KPIs with confidence intervals
        at the configured `confidence_level` (defaults to 95%).
        """
        lines = [
            "\n" + "=" * 60,
            "  Multi-Run Statistics  ({} replications)".format(self.n),
            "  Confidence level: {:.0f}%    Relative precision: {:.0f}%".format(
                self.confidence_level * 100, self.relative_precision * 100),
            "=" * 60,
        ]
        for kpi in ['avg_satisfaction', 'avg_visit_duration',
                    'total_revenue', 'total_entities']:
            try:
                mean, lo, hi = self.confidence_interval(kpi)
                lines.append(
                    "  {:25s}: mean={:9.3f}  CI=[{:.3f}, {:.3f}]".format(
                        kpi, mean, lo, hi))
            except Exception as e:
                lines.append("  {}: ERROR — {}".format(kpi, e))
        lines.append("=" * 60 + "\n")
        return "\n".join(lines)
