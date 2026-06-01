"""
distributions.py
================
All probability-distribution sampling functions used by the simulation.

The project brief requires that every random variate be generated from
U(0, 1) via one of the algorithms taught in class:

  Box-Muller        - Normal distributions
                      Used for: charging battery level, body-art glitter,
                                food ordering service time, and (after
                                fitting) MainStage show duration.

  Inverse Transform - Exponential, Uniform (continuous & discrete)
                      Used for: most arrival processes, SideStage show
                                duration, food prep times, henna body-art,
                                FriendsGroup size, etc.

  Composition       - Piecewise PDFs that split naturally into pieces
                      Used for: PhotoStation service duration (3 linear
                                pieces over [1, 4]).

  Accept-Reject     - Bounded PDFs without a closed-form inverse CDF
                      Used for: DJStage stay duration (piecewise PDF
                                over [20, 60] with a triangular shape).

Additionally this module exposes:
  - sample_charging_duration : power-law CDF, closed-form inverse
  - load_sample_data         : reads the two-sheet Excel file
  - fit_*                    : MLE fits for Exponential / Normal / Uniform
  - kolmogorov_smirnov_statistic : KS goodness-of-fit metric

Each sampler documents the PDF / CDF / inverse-CDF (or the proposal +
acceptance test for accept-reject) in its docstring so the report can
quote the formulas directly.
"""

import math
import random
from typing import Optional, List, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# 1. PRIMITIVE UNIFORM SAMPLER
# ─────────────────────────────────────────────────────────────────────────────

def sample_uniform_01() -> float:
    """Draw a single U(0, 1) sample."""
    return random.random()


# ─────────────────────────────────────────────────────────────────────────────
# 2. BOX-MULLER TRANSFORM  →  Normal distribution
# ─────────────────────────────────────────────────────────────────────────────

class BoxMuller:
    """
    Generates Normal(mu, sigma) samples via the Box-Muller transform.

    The transform converts two independent U(0,1) variates (u1, u2) into
    two independent standard-normal variates:
        Z1 = sqrt(-2 ln u1) * cos(2π u2)
        Z2 = sqrt(-2 ln u1) * sin(2π u2)
    Then X = mu + sigma * Z is returned.

    We cache the second variate Z2 to avoid wasting it.
    """

    def __init__(self):
        self._cached: Optional[float] = None

    def reset(self) -> None:
        """Drop the cached variate. Call between simulation runs so that
        a cached Z2 from a previous (un-seeded) run doesn't leak into a
        freshly seeded run and break reproducibility."""
        self._cached = None

    def sample(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        """Return one Normal(mu, sigma) sample."""
        if self._cached is not None:
            z = self._cached
            self._cached = None
            return mu + sigma * z

        u1 = sample_uniform_01()
        u2 = sample_uniform_01()
        # Avoid log(0)
        while u1 == 0.0:
            u1 = sample_uniform_01()

        magnitude = math.sqrt(-2.0 * math.log(u1))
        z1 = magnitude * math.cos(2.0 * math.pi * u2)
        z2 = magnitude * math.sin(2.0 * math.pi * u2)

        self._cached = z2
        return mu + sigma * z1


# Module-level singleton so all callers share the cached variate
_box_muller = BoxMuller()


def sample_normal(mu: float, sigma: float) -> float:
    """Sample from Normal(mu, sigma) using Box-Muller."""
    return _box_muller.sample(mu, sigma)


def reset_box_muller() -> None:
    """Reset the Box-Muller cache. Call at the start of each replication."""
    _box_muller.reset()


# ─────────────────────────────────────────────────────────────────────────────
# 3. INVERSE TRANSFORM  →  Exponential, Uniform
# ─────────────────────────────────────────────────────────────────────────────

def sample_exponential(mean: float) -> float:
    """
    Sample from Exponential(mean) via Inverse Transform.

    CDF: F(x) = 1 - exp(-x / mean)
    Inverse: x = -mean * ln(1 - U)  =  -mean * ln(U)   (U = 1-U is also uniform)
    """
    u = sample_uniform_01()
    while u == 0.0:
        u = sample_uniform_01()
    return -mean * math.log(u)


def sample_continuous_uniform(a: float, b: float) -> float:
    """
    Sample from Uniform(a, b) via Inverse Transform.

    CDF: F(x) = (x - a) / (b - a)
    Inverse: x = a + (b - a) * U
    """
    u = sample_uniform_01()
    return a + (b - a) * u


def sample_discrete_uniform(a: int, b: int) -> int:
    """
    Sample from Discrete Uniform {a, a+1, ..., b} via Inverse Transform.

    Maps U(0,1) → integer in [a, b] with equal probability 1/(b-a+1).
    """
    u = sample_uniform_01()
    return a + int(u * (b - a + 1))


def sample_poisson(lam: float) -> int:
    """
    Sample from Poisson(lambda) via Inverse Transform (sequential method).

    Used for fitting/generating arrival count data.
    """
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= sample_uniform_01()
    return k - 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. COMPOSITION METHOD  →  PhotoStation duration
# ─────────────────────────────────────────────────────────────────────────────
#
# PDF of photo session duration (x in minutes):
#   f(x) = x/6,         1 <= x < 2   (linear, triangular-like piece)
#   f(x) = x/5 + 1/8,   2 <= x < 3
#   f(x) = 1/8,         3 <= x < 4
#
# We verify the pdf integrates to 1:
#   ∫[1,2] x/6 dx = [x²/12]_1^2 = (4-1)/12 = 3/12 = 1/4
#   ∫[2,3] (x/5 + 1/8) dx = [x²/10 + x/8]_2^3
#                          = (9/10+3/8) - (4/10+2/8)
#                          = (9/10-4/10) + (3/8-2/8) = 1/2 + 1/8 = 5/8
#   ∫[3,4] 1/8 dx = 1/8
#   Total = 1/4 + 5/8 + 1/8 = 2/8 + 5/8 + 1/8 = 8/8 = 1  ✓
#
# Component weights: w1=1/4, w2=5/8, w3=1/8
# Conditional CDFs:
#   Piece 1 (w1=0.25): F1(x) = (x²-1)/3       → x = sqrt(1 + 3U)
#   Piece 2 (w2=0.625): normalised density = (x/5+1/8)/(5/8)
#     F2(x|2<=x<3) = (x²/10 + x/8 - (4/10+2/8)) / (5/8)
#     Solve for x via quadratic: x²/10 + x/8 - C = 0 where C = F2*5/8 + (4/10+2/8)
#   Piece 3 (w3=0.125): F3(x|3<=x<4) = (x-3)  → x = 3 + U
#

_PHOTO_W1 = 1 / 4
_PHOTO_W2 = 5 / 8
_PHOTO_W3 = 1 / 8


def _photo_piece1_inverse(u: float) -> float:
    """Inverse CDF for piece 1: x in [1,2), f(x)=x/6."""
    # CDF on [1,2]: F(x) = (x² - 1) / 3  (normalised to interval weight 1/4 not needed here
    # because we sample conditional on being in piece 1)
    # Solving F(x) = U: x = sqrt(1 + 3*U)
    return math.sqrt(1.0 + 3.0 * u)


def _photo_piece2_inverse(u: float) -> float:
    """Inverse CDF for piece 2: x in [2,3), f(x)=x/5+1/8."""
    # Conditional CDF (normalised so it integrates to 1 on [2,3)):
    #   F2(x) = [x²/10 + x/8 - (4/10 + 2/8)] / (5/8)
    # Set F2(x) = U:
    #   x²/10 + x/8 = U*(5/8) + 4/10 + 2/8
    #   x²/10 + x/8 - C = 0   where C = 5U/8 + 4/10 + 2/8
    # Multiply through by 40:
    #   4x² + 5x - 40C = 0
    C = (5.0 / 8.0) * u + 4.0 / 10.0 + 2.0 / 8.0
    a_coef, b_coef, c_coef = 4.0, 5.0, -40.0 * C
    disc = b_coef ** 2 - 4.0 * a_coef * c_coef
    return (-b_coef + math.sqrt(disc)) / (2.0 * a_coef)


def _photo_piece3_inverse(u: float) -> float:
    """Inverse CDF for piece 3: x in [3,4), f(x)=1/8 (uniform)."""
    return 3.0 + u


def sample_photo_duration() -> float:
    """
    Sample photo session duration using the Composition method.

    Steps:
        1. Pick component with probability proportional to weights.
        2. Sample from that component's conditional distribution.
    """
    u_comp = sample_uniform_01()
    u_val  = sample_uniform_01()

    if u_comp < _PHOTO_W1:                      # piece 1, weight 1/4
        return _photo_piece1_inverse(u_val)
    elif u_comp < _PHOTO_W1 + _PHOTO_W2:        # piece 2, weight 5/8
        return _photo_piece2_inverse(u_val)
    else:                                        # piece 3, weight 1/8
        return _photo_piece3_inverse(u_val)


# ─────────────────────────────────────────────────────────────────────────────
# 5. ACCEPT-REJECT  →  DJStage duration
# ─────────────────────────────────────────────────────────────────────────────
#
# PDF of DJ stage stay duration (x in minutes):
#   f(x) = (x - 20) / 600,            20 <= x <= 40
#   f(x) = (60 - x) / 600 + 1/30,     40 <= x <= 50
#   f(x) = (60 - x) / 600,            50 <= x <= 60
#   f(x) = 0,                          otherwise
#
# Support: [20, 60].  We use U[20,60] as the proposal distribution g(x)=1/40.
# Maximum of f(x):
#   At x=40: f(40) = 20/600 = 1/30
#   At x=40 (from right): f(40) = 20/600 + 1/30 = 1/30 + 1/30 = 2/30 = 1/15
#   So f_max = 1/15
# Acceptance constant c = f_max / g(x) = (1/15) / (1/40) = 40/15 = 8/3
#

_DJ_SUPPORT_MIN = 20.0
_DJ_SUPPORT_MAX = 60.0
_DJ_F_MAX       = 1.0 / 15.0
_DJ_G           = 1.0 / (_DJ_SUPPORT_MAX - _DJ_SUPPORT_MIN)   # 1/40
_DJ_C           = _DJ_F_MAX / _DJ_G                            # 8/3


def _dj_pdf(x: float) -> float:
    """Evaluate the DJStage stay-duration PDF at x."""
    if 20.0 <= x <= 40.0:
        return (x - 20.0) / 600.0
    elif 40.0 < x <= 50.0:
        return (60.0 - x) / 600.0 + 1.0 / 30.0
    elif 50.0 < x <= 60.0:
        return (60.0 - x) / 600.0
    else:
        return 0.0


def sample_dj_duration() -> float:
    """
    Sample DJStage stay duration using the Accept-Reject method.

    Proposal: Uniform[20, 60].
    Accept x if U <= f(x) / (c * g(x)).
    """
    while True:
        x = sample_continuous_uniform(_DJ_SUPPORT_MIN, _DJ_SUPPORT_MAX)
        u = sample_uniform_01()
        if u <= _dj_pdf(x) / (_DJ_C * _DJ_G):
            return x


# ─────────────────────────────────────────────────────────────────────────────
# 6. CHARGING STATION  →  custom power-law CDF
# ─────────────────────────────────────────────────────────────────────────────
#
# Battery level b ~ Normal(40, 15)  (clamped to [0, 100))
# alpha = 100 / (100 - b)
#
# f(t) = (alpha / 40^alpha) * (40 - t)^(alpha-1),  0 <= t <= 40
#
# CDF: F(t) = 1 - ((40-t)/40)^alpha
# Inverse CDF: t = 40 * (1 - (1-U)^(1/alpha))
#

def sample_charging_duration(battery_level):
    """
    Sample charging duration given the entity's battery level.

    Args:
        battery_level: percentage in [0, 100) from Normal(40,15).
    """
    # Clamp battery level to [0, 99.9]
    if battery_level < 0.0:
        battery_level = 0.0
    if battery_level > 99.9:
        battery_level = 99.9

    alpha = 100.0 / (100.0 - battery_level)
    u = sample_uniform_01()
    # Inverse CDF: t = 40 * (1 - (1-U)^(1/alpha))
    return 40.0 * (1.0 - (1.0 - u) ** (1.0 / alpha))


def sample_battery_level(cfg_mean=40.0, cfg_std=15.0):
    """Sample battery arrival percentage ~ Normal(mean, std), clamped to [0, 99.9]."""
    b = sample_normal(cfg_mean, cfg_std)

    if b < 0.0:
        b = 0.0
    if b > 99.9:
        b = 99.9

    return b


# ─────────────────────────────────────────────────────────────────────────────
# 7. CONVENIENCE WRAPPERS for common distributions used in the simulation
# ─────────────────────────────────────────────────────────────────────────────

def sample_body_art_duration(art_type):
    """
    Sample body art service duration by art type.
        'glitter': Normal(15, 3) via Box-Muller
        'neon'   : Exponential(12) via Inverse Transform
        'henna'  : Uniform[17, 22] via Inverse Transform
    """
    if art_type == 'glitter':
        duration = sample_normal(15.0, 3.0)
        if duration < 1.0:
            duration = 1.0
        return duration
    elif art_type == 'neon':
        return sample_exponential(12.0)
    elif art_type == 'henna':
        return sample_continuous_uniform(17.0, 22.0)
    else:
        raise ValueError("Unknown art type: " + str(art_type))


def sample_food_service_time(food_service_mean=5.0, food_service_std=1.5):
    """Order/payment service time ~ Normal(5, 1.5), minimum 0.5 min."""
    duration = sample_normal(food_service_mean, food_service_std)
    if duration < 0.5:
        duration = 0.5
    return duration


def sample_art_type() -> str:
    """Choose body-art type: 'glitter'(0.3), 'neon'(0.3), 'henna'(0.4)."""
    u = sample_uniform_01()
    if u < 0.3:
        return 'glitter'
    elif u < 0.6:
        return 'neon'
    else:
        return 'henna'


def sample_food_restaurant(burger_prob: float, pizza_prob: float) -> str:
    """Choose restaurant based on configured probabilities."""
    u = sample_uniform_01()
    if u < burger_prob:
        return 'burger'
    elif u < burger_prob + pizza_prob:
        return 'pizza'
    else:
        return 'asian'


# ─────────────────────────────────────────────────────────────────────────────
# 8. DISTRIBUTION FITTING  (for samples_for_simulation.xlsx)
# ─────────────────────────────────────────────────────────────────────────────

def fit_exponential(data: List[float]) -> float:
    """
    Fit Exponential distribution to data via MLE.
    MLE estimate: lambda_hat = 1 / x_bar  → mean = x_bar
    """
    if not data:
        raise ValueError("Empty dataset")
    return sum(data) / len(data)


def fit_normal(data: List[float]) -> Tuple[float, float]:
    """
    Fit Normal distribution via MLE.
    Returns (mu, sigma).
    """
    n = len(data)
    if n < 2:
        raise ValueError("Need at least 2 data points")
    mu = sum(data) / n
    sigma = math.sqrt(sum((x - mu) ** 2 for x in data) / (n - 1))
    return mu, sigma


def fit_uniform(data: List[float]) -> Tuple[float, float]:
    """
    Fit Uniform(a, b) distribution via MLE.
    MLE: a = min(data), b = max(data).
    """
    return min(data), max(data)


def kolmogorov_smirnov_statistic(data: List[float],
                                  cdf_func) -> float:
    """
    Compute the KS test statistic D = max |F_n(x) - F(x)|.
    Used to evaluate goodness-of-fit for a candidate distribution.
    """
    sorted_data = sorted(data)
    n = len(sorted_data)
    d_max = 0.0
    for i, x in enumerate(sorted_data):
        f_empirical_upper = (i + 1) / n
        f_empirical_lower = i / n
        f_theoretical = cdf_func(x)
        d_max = max(d_max,
                    abs(f_empirical_upper - f_theoretical),
                    abs(f_empirical_lower - f_theoretical))
    return d_max


def load_sample_data(xlsx_path: str) -> dict:
    """
    Load the two sheets from samples_for_simulation.xlsx.
    Returns dict with keys 'sheet1' and 'sheet2' containing lists of values.

    NOTE: Sheet 1 is assumed to contain FriendsGroup inter-arrival times.
          Sheet 2 is assumed to contain MainStage performance durations.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
        result = {}
        for name in wb.sheetnames:
            ws = wb[name]
            values = []
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if isinstance(cell, (int, float)) and cell is not None:
                        values.append(float(cell))
            result[name] = values
        wb.close()
        return result
    except Exception as e:
        print(f"[WARNING] Could not load Excel data: {e}")
        return {}
