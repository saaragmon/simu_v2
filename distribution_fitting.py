"""
distribution_fitting.py
=======================
Loads sample data from the Excel file and fits distributions for:
    Sheet 1 – FriendsGroup inter-arrival times
    Sheet 2 – MainStage show durations

After fitting, returns callable samplers that can be injected into the engine.

Usage:
    from distribution_fitting import fit_from_excel
    samplers = fit_from_excel('samples_for_simulation.xlsx')
    sim = Simulation(
        cfg,
        friends_arrival_sampler     = samplers['friends_interarrival'],
        main_stage_duration_sampler = samplers['main_stage_duration'],
    )
"""

from __future__ import annotations
import math
from typing import Callable, Dict, List, Optional, Tuple

from distributions import (
    fit_exponential, fit_normal, fit_uniform,
    kolmogorov_smirnov_statistic,
    sample_exponential, sample_normal, sample_continuous_uniform,
    load_sample_data,
)


# ─────────────────────────────────────────────────────────────────────────────
# CDF helpers for KS test
# ─────────────────────────────────────────────────────────────────────────────

def _exponential_cdf(mean: float) -> Callable[[float], float]:
    return lambda x: 1.0 - math.exp(-x / mean) if x >= 0 else 0.0


def _normal_cdf(mu: float, sigma: float) -> Callable[[float], float]:
    def cdf(x: float) -> float:
        z = (x - mu) / sigma
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return cdf


def _uniform_cdf(a: float, b: float) -> Callable[[float], float]:
    return lambda x: max(0.0, min(1.0, (x - a) / (b - a)))


# ─────────────────────────────────────────────────────────────────────────────
# Fit candidate distributions and select best via KS statistic
# ─────────────────────────────────────────────────────────────────────────────

def best_fit(data: List[float], label: str = '') -> Tuple[str, dict, Callable]:
    """
    Try Exponential, Normal, and Uniform fits on the data.
    Select the distribution with the smallest KS statistic.

    Returns:
        (dist_name, params_dict, sampler_callable)
    """
    if not data:
        raise ValueError(f"Empty data for '{label}'")

    candidates = {}

    # Exponential
    mean_exp = fit_exponential(data)
    ks_exp   = kolmogorov_smirnov_statistic(data, _exponential_cdf(mean_exp))
    candidates['Exponential'] = {
        'ks': ks_exp,
        'params': {'mean': mean_exp},
        'sampler': lambda m=mean_exp: sample_exponential(m),
    }

    # Normal
    mu_n, sigma_n = fit_normal(data)
    ks_norm       = kolmogorov_smirnov_statistic(data, _normal_cdf(mu_n, sigma_n))
    candidates['Normal'] = {
        'ks': ks_norm,
        'params': {'mu': mu_n, 'sigma': sigma_n},
        'sampler': lambda m=mu_n, s=sigma_n: max(0.1, sample_normal(m, s)),
    }

    # Uniform
    a_u, b_u = fit_uniform(data)
    ks_uni   = kolmogorov_smirnov_statistic(data, _uniform_cdf(a_u, b_u))
    candidates['Uniform'] = {
        'ks': ks_uni,
        'params': {'a': a_u, 'b': b_u},
        'sampler': lambda a=a_u, b=b_u: sample_continuous_uniform(a, b),
    }

    # Choose best
    best_name = min(candidates, key=lambda k: candidates[k]['ks'])
    best      = candidates[best_name]

    print(f"\n[Distribution Fitting] '{label}'")
    print(f"  n = {len(data)}")
    for name, info in candidates.items():
        mark = ' ◄ SELECTED' if name == best_name else ''
        print(f"  {name:12s}: KS={info['ks']:.4f}  params={info['params']}{mark}")

    return best_name, best['params'], best['sampler']


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fit_from_excel(xlsx_path: str) -> Dict[str, Callable]:
    """
    Load Excel sample data and fit distributions for each sheet.

    Returns a dict of callables:
        'friends_interarrival'  – inter-arrival time sampler (minutes)
        'main_stage_duration'   – show duration sampler (minutes)

    If the file cannot be read, falls back to sensible defaults.
    """
    sheets = load_sample_data(xlsx_path)

    samplers: Dict[str, Callable] = {}

    # ── Sheet 1: FriendsGroup inter-arrival times ─────────────────────────────
    sheet1_key = list(sheets.keys())[0] if sheets else None
    if sheet1_key and sheets[sheet1_key]:
        data1 = sheets[sheet1_key]
        _, _, sampler1 = best_fit(data1, label='FriendsGroup inter-arrival (min)')
        samplers['friends_interarrival'] = sampler1
    else:
        print("[WARNING] Sheet 1 not loaded – using default Exponential(5 min) "
              "for FriendsGroup arrivals.")
        samplers['friends_interarrival'] = lambda: sample_exponential(5.0)

    # ── Sheet 2: MainStage show durations ─────────────────────────────────────
    sheet2_key = list(sheets.keys())[1] if len(sheets) > 1 else None
    if sheet2_key and sheets[sheet2_key]:
        data2 = sheets[sheet2_key]
        _, _, sampler2 = best_fit(data2, label='MainStage show duration (min)')
        samplers['main_stage_duration'] = sampler2
    else:
        print("[WARNING] Sheet 2 not loaded – using default Exponential(60 min) "
              "for MainStage durations.")
        samplers['main_stage_duration'] = lambda: sample_exponential(60.0)

    return samplers
