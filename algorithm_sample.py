"""
algorithm_sample.py
===================
All random-variate samplers for the Queuechella festival simulation,
collected in one class.

Every method uses exactly one of the four techniques taught in class:
  - Inverse Transform
  - Composition
  - Accept-Reject
  - Box-Muller

No external libraries are used – only math and random.
"""

import math
import random


class AlgorithmSample:

    # ─────────────────────────────────────────────────────────────────────
    # INVERSE TRANSFORM
    # ─────────────────────────────────────────────────────────────────────

    # -- Exponential: inter-arrival times ----------------------------------
    #
    # CDF:     F(x) = 1 - e^(-x / mean)
    # Inverse: x = -mean * ln(U)
    #
    # Used for: FriendsGroup, Couple, Single inter-arrival times,
    #           and EntryGate security check duration.

    @staticmethod
    def friends_interarrival_time(mean=15.0):
        """FriendsGroup inter-arrival time ~ Exponential(mean) in minutes."""
        u = random.random()
        return -mean * math.log(u)

    @staticmethod
    def couple_interarrival_time(mean=1.0):
        """Couple inter-arrival time ~ Exponential(mean) in minutes."""
        u = random.random()
        return -mean * math.log(u)

    @staticmethod
    def single_interarrival_time(mean=0.84):
        """Single inter-arrival time ~ Exponential(mean) in minutes."""
        u = random.random()
        return -mean * math.log(u)

    @staticmethod
    def entry_security_duration(mean=2.0):
        """Security check duration ~ Exponential(mean=2) in minutes."""
        u = random.random()
        return -mean * math.log(u)

    # -- Uniform (continuous): service times where only range is known -----
    #
    # CDF:     F(x) = (x - a) / (b - a)
    # Inverse: x = a + (b - a) * U

    @staticmethod
    def entry_scan_duration(a=1.5, b=3.0):
        """Entry ticket scan ~ Uniform[1.5, 3.0] minutes."""
        u = random.random()
        return a + (b - a) * u

    @staticmethod
    def merch_service_duration(a=2.0, b=6.0):
        """MerchTent cashier service ~ Uniform[2, 6] minutes."""
        u = random.random()
        return a + (b - a) * u

    @staticmethod
    def side_stage_duration(a=20.0, b=30.0):
        """SideStage show duration ~ Uniform[20, 30] minutes."""
        u = random.random()
        return a + (b - a) * u

    @staticmethod
    def food_eating_duration(a=15.0, b=35.0):
        """Food eating time ~ Uniform[15, 35] minutes."""
        u = random.random()
        return a + (b - a) * u

    @staticmethod
    def food_prep_duration(restaurant='burger'):
        """
        Food preparation time ~ Uniform[a, b] minutes.
        Ranges:  burger [3, 4],  pizza [4, 6],  asian [3, 7]
        """
        u = random.random()
        if restaurant == 'burger':
            return 3.0 + (4.0 - 3.0) * u
        elif restaurant == 'pizza':
            return 4.0 + (6.0 - 4.0) * u
        else:  # asian
            return 3.0 + (7.0 - 3.0) * u

    # ─────────────────────────────────────────────────────────────────────
    # COMPOSITION
    # ─────────────────────────────────────────────────────────────────────
    #
    # PhotoStation session duration (x in minutes):
    #
    #   f(x) = x/6,          1 <= x < 2   weight w1 = 1/4
    #   f(x) = x/5 + 1/8,    2 <= x < 3   weight w2 = 5/8
    #   f(x) = 1/8,          3 <= x < 4   weight w3 = 1/8
    #
    # For each piece the conditional inverse CDF is derived and used.
    #
    # Piece 1: F1(x) = (x² - 1) / 3   →  x = sqrt(1 + 3U)
    # Piece 2: 4x² + 5x - 40C = 0,  C = 5U/8 + 0.65  →  quadratic formula
    # Piece 3: F3(x) = x - 3  (uniform on [3,4])  →  x = 3 + U

    @staticmethod
    def photo_station_duration():
        """Sample PhotoStation session duration using the Composition method."""
        W1, W2 = 1/4, 5/8      # piece weights; W3 = 1/8 (the rest)

        u_pick = random.random()   # choose which piece
        u_val  = random.random()   # sample within that piece

        if u_pick < W1:
            # Piece 1: x = sqrt(1 + 3U)
            return math.sqrt(1.0 + 3.0 * u_val)

        elif u_pick < W1 + W2:
            # Piece 2: solve 4x² + 5x - 40C = 0
            C = (5.0 / 8.0) * u_val + 4.0 / 10.0 + 2.0 / 8.0
            disc = 25.0 + 4.0 * 4.0 * 40.0 * C
            return (-5.0 + math.sqrt(disc)) / (2.0 * 4.0)

        else:
            # Piece 3: x = 3 + U  (uniform on [3, 4])
            return 3.0 + u_val

    # ─────────────────────────────────────────────────────────────────────
    # ACCEPT-REJECT
    # ─────────────────────────────────────────────────────────────────────
    #
    # DJStage stay duration (x in minutes):
    #
    #   f(x) = (x - 20) / 600,              20 <= x <= 40
    #   f(x) = (60 - x) / 600 + 1/30,       40 <  x <= 50
    #   f(x) = (60 - x) / 600,              50 <  x <= 60
    #
    # Proposal g(x) = Uniform[20, 60]  →  g(x) = 1/40
    # Maximum of f(x) = 1/15  (at x = 40 from the right)
    # Acceptance constant c = f_max / g = (1/15) / (1/40) = 8/3
    #
    # Accept x if  U <= f(x) / (c * g(x))

    @staticmethod
    def _dj_pdf(x):
        if 20.0 <= x <= 40.0:
            return (x - 20.0) / 600.0
        elif 40.0 < x <= 50.0:
            return (60.0 - x) / 600.0 + 1.0 / 30.0
        elif 50.0 < x <= 60.0:
            return (60.0 - x) / 600.0
        return 0.0

    @staticmethod
    def dj_stage_duration():
        """Sample DJStage stay duration using the Accept-Reject method."""
        C   = 8.0 / 3.0   # acceptance constant
        G   = 1.0 / 40.0  # proposal density (Uniform[20,60])
        while True:
            # Sample from proposal: Uniform[20, 60]
            x = 20.0 + 40.0 * random.random()
            u = random.random()
            if u <= AlgorithmSample._dj_pdf(x) / (C * G):
                return x

    # ─────────────────────────────────────────────────────────────────────
    # BOX-MULLER
    # ─────────────────────────────────────────────────────────────────────
    #
    # Converts two independent U(0,1) variates into a Normal(mu, sigma):
    #   Z = sqrt(-2 * ln(U1)) * cos(2π * U2)
    #   X = mu + sigma * Z
    #
    # Used for: MainStage show duration, body-art glitter duration,
    #           food ordering service time, and battery arrival level.

    @staticmethod
    def _box_muller_standard():
        """Return one standard Normal(0,1) variate via Box-Muller."""
        u1 = random.random()
        while u1 == 0.0:       # avoid log(0)
            u1 = random.random()
        u2 = random.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    @staticmethod
    def main_stage_duration(mu, sigma):
        """MainStage show duration ~ Normal(mu, sigma), minimum 10 minutes."""
        duration = mu + sigma * AlgorithmSample._box_muller_standard()
        return max(duration, 10.0)

    @staticmethod
    def body_art_glitter_duration(mu=15.0, sigma=3.0):
        """Glitter body-art service ~ Normal(15, 3), minimum 1 minute."""
        duration = mu + sigma * AlgorithmSample._box_muller_standard()
        return max(duration, 1.0)

    @staticmethod
    def food_service_duration(mu=5.0, sigma=1.5):
        """Food order/payment service time ~ Normal(5, 1.5), minimum 0.5 min."""
        duration = mu + sigma * AlgorithmSample._box_muller_standard()
        return max(duration, 0.5)

    @staticmethod
    def battery_level(mu=40.0, sigma=15.0):
        """Visitor battery level on arrival ~ Normal(40, 15), clamped to [0, 99.9]."""
        level = mu + sigma * AlgorithmSample._box_muller_standard()
        if level < 0.0:
            level = 0.0
        if level > 99.9:
            level = 99.9
        return level
