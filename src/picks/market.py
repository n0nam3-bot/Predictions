"""Odds math. American odds in, probabilities out."""


def american_to_decimal(odds):
    odds = float(odds)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)


def american_to_implied(odds):
    return 1 / american_to_decimal(odds)


def prob_to_american(p):
    if not 0 < p < 1:
        raise ValueError("probability must be between 0 and 1")
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def no_vig_two_way(odds_a, odds_b, method="proportional"):
    """Return (prob_a, prob_b, overround) with the vig removed."""
    ia, ib = american_to_implied(odds_a), american_to_implied(odds_b)
    total = ia + ib
    if method == "proportional":
        pa = ia / total
    elif method == "power":          # solve ia**k + ib**k = 1
        lo, hi = 0.5, 5.0
        for _ in range(80):
            k = (lo + hi) / 2
            if ia ** k + ib ** k > 1:
                lo = k
            else:
                hi = k
        pa = ia ** ((lo + hi) / 2)
    else:
        raise ValueError(f"unknown method {method}")
    return pa, 1 - pa, total - 1


def ev_per_unit(p_win, american):
    """Expected profit per unit staked at the quoted price."""
    return p_win * american_to_decimal(american) - 1


def profit_units(american, units=1.0):
    """Profit on a winning bet of `units`."""
    american = float(american)
    return units * american / 100 if american > 0 else units * 100 / abs(american)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def units_for(edge, coverage, max_units=3):
    return int(clamp(round(edge / 0.02 * coverage), 1, max_units))


def confidence_for(edge, coverage):
    return int(clamp(round(10 * coverage * min(edge / 0.08, 1.0)), 1, 10))
