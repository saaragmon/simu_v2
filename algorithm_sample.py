import math
import random


class AlgorithmSample:

    # INVERSE TRANSFORM ----------------------------------------------------------------------

    @staticmethod
    def friends_group_size(a: int = 3, b: int = 6) -> int:
        """
        FriendsGroup size ~ Discrete Uniform{a, a+1, ..., b} via Inverse Transform.

        CDF: F(k) = (k - a + 1) / (b - a + 1)  for k in {a,...,b}
        Inverse: k = a + floor(U * (b - a + 1))
        """
        u = random.random()
        return a + int(u * (b - a + 1))

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

    # -- Uniform (continuous): service times where only range is known ----------------

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

    
    # COMPOSITION----------------------------------------------------------------------    

    @staticmethod
    def photo_station_duration(): #using recycled u for less random calls
        u = random.random()

        if u < 0.25:
            # Piece 1: 1 <= x < 2
            # Recycle u from [0, 0.25) to [0, 1)
            u_recycled = u / 0.25
            return math.sqrt(1.0 + 3.0 * u_recycled)

        elif u < 0.875:  # 0.25 + 0.625
            # Piece 2: 2 <= x < 3
            # Recycle u from [0.25, 0.875) to [0, 1)
            u_recycled = (u - 0.25) / 0.625
            discriminant = 441.0 + 400.0 * u_recycled
            return (-5.0 + math.sqrt(discriminant)) / 8.0

        else:
            # Piece 3: 3 <= x < 4
            # Recycle u from [0.875, 1.0) to [0, 1)
            u_recycled = (u - 0.875) / 0.125
            return 3.0 + u_recycled
    # ACCEPT-REJECT ----------------------------------------------------------------------

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
        C    = 8.0 / 3.0   # acceptance constant
        G    = 1.0 / 40.0  # proposal density (Uniform[20,60])
        CG   = C * G       # pre-computed product (constant across iterations)
        while True:
            # Sample from proposal: Uniform[20, 60]
            x = 20.0 + 40.0 * random.random()
            u = random.random()
            if u <= AlgorithmSample._dj_pdf(x) / CG:
                return x

    # BOX-MULLER ----------------------------------------------------------------------

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
        return max(0.0, min(99.9, level))

    @staticmethod
    def charging_station_duration(battery_level: float) -> float:
        """
        Charging duration ~ power-law distribution via Inverse Transform.

        PDF:  f(t) = (alpha / 40^alpha) * (40 - t)^(alpha-1),  0 <= t <= 40
        CDF:  F(t) = 1 - ((40 - t) / 40)^alpha
        Inverse CDF: t = 40 * (1 - (1 - U)^(1/alpha))

        where alpha = 100 / (100 - b),  b = battery percentage in [0, 99.9].
        Higher battery → larger alpha → entity charges for less time.
        """
        b = max(0.0, min(99.9, battery_level))
        alpha = 100.0 / (100.0 - b)
        u = random.random()
        return 40.0 * (1.0 - (1.0 - u) ** (1.0 / alpha))
