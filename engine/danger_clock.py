"""Danger clock: how many minutes until each patient's device loses power.

- Patient on a cut circuit: only the device's internal battery is left.
- Patient on a kept circuit: the generator runs until the fuel is gone; if the
  diesel tanker arrives first, they are covered.
"""
from __future__ import annotations

import pandas as pd

from engine import fuel
from engine.model import Hospital
from engine.plan import Plan, circuit_loads, patient_status


def danger_clock(h: Hospital, plan: Plan, rules: dict, min_weight: int = 40) -> pd.DataFrame:
    g = h.generator
    kept_kw = circuit_loads(h, plan, rules)["load_kw"].sum()
    runtime_min = fuel.runtime_h(g["fuel_l"], kept_kw, g["rated_kw"]) * 60
    refuel_min = g["refuel_eta_h"] * 60
    pts = patient_status(h, plan, rules)
    pts = pts[pts["weight"] >= min_weight].copy()
    rooms = h.rooms.set_index("id")["name"]

    def clock(row):
        if not row["powered"]:
            return row["battery_min"], "Circuit cut - device battery only"
        if runtime_min >= refuel_min:
            return float("inf"), "Covered until diesel tanker arrives"
        return runtime_min + row["battery_min"], "Generator fuel runs out first"

    vals = pts.apply(clock, axis=1, result_type="expand")
    pts["minutes_left"], pts["reason"] = vals[0], vals[1]
    pts["level"] = pd.cut(pts["minutes_left"], [-1, 30, 120, float("inf")],
                          labels=["RED", "AMBER", "GREEN"], include_lowest=True).astype(str)
    pts.loc[pts["minutes_left"] == float("inf"), "level"] = "GREEN"
    pts["room"] = pts["final_room"].map(rooms)
    cols = ["level", "minutes_left", "id", "name", "devices", "room", "circuit_id",
            "life_support", "reason"]
    return pts.sort_values(["minutes_left", "weight"], ascending=[True, False])[cols]
