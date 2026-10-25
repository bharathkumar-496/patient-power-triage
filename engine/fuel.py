"""Diesel generator fuel model.

Uses the linear "Willans line" fuel curve with HOMER Pro's default coefficients
(assumed - replace with the real generator's datasheet values):

    fuel (L/h) = A x rated_kW + B x load_kW
    A = 0.08145 L/h per kW of rating  (no-load burn)
    B = 0.246   L/h per kW of output

Example: 300 kW set at 250 kW load -> 0.08145*300 + 0.246*250 = 85.9 L/h.
"""
A = 0.08145
B = 0.246


def burn_rate(load_kw: float, rated_kw: float) -> float:
    """Litres per hour. A running generator burns its no-load fuel even at 0 kW."""
    if load_kw <= 0:
        return 0.0
    return A * rated_kw + B * load_kw


def runtime_h(fuel_l: float, load_kw: float, rated_kw: float) -> float:
    """Hours until the tank is empty at a constant load."""
    rate = burn_rate(load_kw, rated_kw)
    return float("inf") if rate == 0 else fuel_l / rate


def fuel_safe_load(fuel_l: float, hours_needed: float, rated_kw: float) -> float:
    """Largest load (kW) that still lets the fuel last `hours_needed`.

    Solves fuel_l / (A*rated + B*load) = hours_needed for load.
    """
    if hours_needed <= 0:
        return rated_kw
    return max(0.0, (fuel_l / hours_needed - A * rated_kw) / B)
