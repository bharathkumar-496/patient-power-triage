"""What-if tests: re-plan under a worse situation and compare."""
from __future__ import annotations

from engine.model import Hospital


def apply_whatif(h: Hospital, gen_fail_pct: float = 0, fuel_drop_pct: float = 0,
                 outage_extra_h: float = 0, refuel_delay_h: float = 0) -> Hospital:
    """Return a copy of the hospital with the given problems applied.

    gen_fail_pct:   lose this % of generator capacity (e.g. 50 = one of two sets fails)
    fuel_drop_pct:  lose this % of the fuel (leak, theft, wrong gauge reading)
    outage_extra_h: the outage lasts this many hours longer than expected
    refuel_delay_h: the diesel tanker is this many hours late
    """
    w = h.copy()
    g = w.generator
    g["rated_kw"] = g["rated_kw"] * (1 - gen_fail_pct / 100)
    g["fuel_l"] = g["fuel_l"] * (1 - fuel_drop_pct / 100)
    g["expected_outage_h"] = g["expected_outage_h"] + outage_extra_h
    g["refuel_eta_h"] = g["refuel_eta_h"] + refuel_delay_h
    return w
