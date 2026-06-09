"""
plot_distributions.py
=====================
Graphical goodness-of-fit comparison for the two sample-data columns in
`samples_for_simulation.xlsx`:

    Sheet 1 — FriendsGroup_arrival_intervals  (minutes)
    Sheet 2 — MainStage_concert_duration       (minutes)

For each column we:
    1. Fit Exponential, Normal, and Uniform via MLE.
    2. Pick the best fit by smallest Kolmogorov-Smirnov statistic
       (same logic the simulation uses in `distribution_fitting.py`).
    3. Draw three diagnostic plots for the chosen distribution:
         a) Histogram + KDE density line
         b) QQ plot against the fitted distribution
         c) Empirical CDF vs. fitted CDF
    4. Save the figure to `plots/<column>.png` and also show it.

This mirrors the graphical comparison from the hotel-simulation example
project distributed with the course, adapted for our 3-candidate
fitting workflow.

Usage:
    python3 plot_distributions.py                  # all columns
    python3 plot_distributions.py --no-show        # save only, no popup
    python3 plot_distributions.py --xlsx other.xlsx
"""

from __future__ import annotations

import argparse
import os
from typing import List, Tuple

import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import probplot, expon, norm, uniform

from distributions_delete import load_sample_data
from distribution_fitting import best_fit


# ─── Visual style (matches the hotel example) ────────────────────────────────
UNIFIED_BLUE = "#80CEED"
UNIFIED_PINK = "#FCB8D6"
TEXT_COLOR   = "dimgray"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers that wrap each best-fit distribution as a scipy "frozen" distribution
# so we can hand it to probplot() and compute its CDF uniformly.
# ─────────────────────────────────────────────────────────────────────────────

def _scipy_dist(dist_name: str, params: dict):
    """
    Return a scipy frozen distribution matching our (dist_name, params) pair.

    Our fitter uses three families:
        Exponential(mean)      → scipy.stats.expon(scale=mean)
        Normal(mu, sigma)      → scipy.stats.norm(loc=mu, scale=sigma)
        Uniform(a, b)          → scipy.stats.uniform(loc=a, scale=b-a)
    """
    if dist_name == 'Exponential':
        return expon(loc=0, scale=params['mean'])
    if dist_name == 'Normal':
        return norm(loc=params['mu'], scale=params['sigma'])
    if dist_name == 'Uniform':
        a = params['a']
        b = params['b']
        return uniform(loc=a, scale=b - a)
    raise ValueError(f"Unknown distribution: {dist_name}")


def _theoretical_pdf_curve(dist_name: str, params: dict,
                            x_min: float, x_max: float, n_points: int = 400):
    """Sample (x, pdf(x)) points for overlaying the theoretical density."""
    xs = np.linspace(max(x_min, 1e-9), x_max, n_points)
    frozen = _scipy_dist(dist_name, params)
    return xs, frozen.pdf(xs)


# ─────────────────────────────────────────────────────────────────────────────
# Individual plot panels
# ─────────────────────────────────────────────────────────────────────────────

def histogram_with_density(data: np.ndarray, label: str,
                            dist_name: str, params: dict, ax) -> None:
    """Histogram + theoretical PDF of the chosen fit."""
    # Empirical histogram (density-normalised so it aligns with the PDF)
    ax.hist(data, bins=20, density=True, edgecolor='black', alpha=0.7,
            label='Histogram', color=UNIFIED_BLUE)

    x_lo, x_hi = float(np.min(data)), float(np.max(data))
    pad = 0.05 * (x_hi - x_lo)

    # Theoretical PDF of the fitted distribution
    xs_t, ys_t = _theoretical_pdf_curve(dist_name, params, x_lo, x_hi)
    ax.plot(xs_t, ys_t, color=UNIFIED_PINK, lw=2,
            label=f'Fitted {dist_name} PDF')

    ax.set_title(f"Histogram + Fitted PDF — {label}", color=TEXT_COLOR)
    ax.set_xlabel(f"{label} values", color=TEXT_COLOR)
    ax.set_ylabel('Density', color=TEXT_COLOR)
    ax.set_xlim(left=max(0.0, x_lo - pad))
    ax.legend()


def qq_plot(data: np.ndarray, dist_name: str, params: dict, ax) -> None:
    """QQ plot of the data quantiles against the fitted distribution."""
    if dist_name == 'Exponential':
        probplot(data, dist='expon', sparams=(0, params['mean']), plot=ax)
    elif dist_name == 'Normal':
        probplot(data, dist='norm',
                  sparams=(params['mu'], params['sigma']), plot=ax)
    elif dist_name == 'Uniform':
        probplot(data, dist='uniform',
                  sparams=(params['a'], params['b'] - params['a']), plot=ax)
    else:
        raise ValueError(f"Unknown distribution: {dist_name}")

    # Recolour the regression line and points to match the unified palette
    lines = ax.get_lines()
    if len(lines) >= 2:
        lines[0].set_markerfacecolor(UNIFIED_BLUE)
        lines[0].set_markeredgecolor('black')
        lines[1].set_color(UNIFIED_PINK)
        lines[1].set_linewidth(2.0)
    ax.set_title(f"QQ Plot vs. {dist_name}", color=TEXT_COLOR)
    ax.set_xlabel('Theoretical quantiles', color=TEXT_COLOR)
    ax.set_ylabel('Sample quantiles', color=TEXT_COLOR)


def cdf_plot(data: np.ndarray, dist_name: str, params: dict, ax) -> None:
    """Empirical CDF vs. fitted CDF."""
    sorted_data = np.sort(data)
    n = len(sorted_data)
    empirical = np.arange(1, n + 1) / n

    frozen = _scipy_dist(dist_name, params)
    fitted = frozen.cdf(sorted_data)

    ax.plot(sorted_data, empirical, marker='o', linestyle='', markersize=4,
            label='Empirical CDF', color=UNIFIED_BLUE)
    ax.plot(sorted_data, fitted, color=UNIFIED_PINK, lw=2,
            label=f'Fitted {dist_name} CDF')

    ax.set_title('CDF Comparison', color=TEXT_COLOR)
    ax.set_xlabel('Data', color=TEXT_COLOR)
    ax.set_ylabel('Cumulative probability', color=TEXT_COLOR)
    ax.legend(loc='upper left')


# ─────────────────────────────────────────────────────────────────────────────
# Top-level driver
# ─────────────────────────────────────────────────────────────────────────────

def plot_column(values: List[float], label: str, output_dir: str,
                show: bool) -> Tuple[str, dict]:
    """Run best-fit + 3 diagnostic plots for one column. Returns (dist, params)."""
    data = np.asarray(values, dtype=float)

    # Fit candidates and select best (same routine the simulation uses)
    dist_name, params, _sampler = best_fit(list(data), label=label)

    fig, axs = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle(
        f"{label}  —  best fit: {dist_name}  (n={len(data)})",
        color=UNIFIED_PINK, fontsize=14, fontweight='bold',
    )
    histogram_with_density(data, label, dist_name, params, axs[0])
    qq_plot(data, dist_name, params, axs[1])
    cdf_plot(data, dist_name, params, axs[2])
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    # Save the figure
    os.makedirs(output_dir, exist_ok=True)
    safe = label.replace(' ', '_').replace('/', '_')
    out_path = os.path.join(output_dir, f"{safe}.png")
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    print(f"  Saved figure: {out_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return dist_name, params


def main(args):
    xlsx_path = args.xlsx
    if not os.path.exists(xlsx_path):
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    print(f"Reading: {xlsx_path}")
    sheets = load_sample_data(xlsx_path)
    if not sheets:
        raise RuntimeError("No data loaded from Excel.")

    print(f"Output directory: {args.output_dir}")
    for sheet_name, values in sheets.items():
        if not values:
            print(f"  Skipping empty sheet: {sheet_name!r}")
            continue
        plot_column(values, label=sheet_name,
                     output_dir=args.output_dir, show=not args.no_show)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Graphical goodness-of-fit comparison for sample data.')
    parser.add_argument(
        '--xlsx',
        default=os.path.join(os.path.dirname(__file__),
                              'samples_for_simulation.xlsx'),
        help='Path to the Excel file (default: samples_for_simulation.xlsx)')
    parser.add_argument(
        '--output-dir',
        default=os.path.join(os.path.dirname(__file__), 'plots'),
        help='Directory to save the PNG figures (default: ./plots).')
    parser.add_argument(
        '--no-show', action='store_true',
        help='Do not open plot windows (useful on headless machines).')
    args = parser.parse_args()
    main(args)
