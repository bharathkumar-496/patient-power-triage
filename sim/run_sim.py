"""50-outage simulation: fixed shed list (today) vs patient-aware planner.

Each scenario is a different night in the fake hospital: census, ICU overflow,
wiring faults, generator size, fuel level, outage length, tanker delay.
Both methods plan on what staff know (the *expected* outage length); results
are judged on what really happens (the *actual* outage length).

    .venv/bin/python -m sim.run_sim            # 50 scenarios + sensitivity runs
    .venv/bin/python -m sim.run_sim --quick    # 50 scenarios only
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

from data.generate import make_hospital
from engine import fuel
from engine.baseline import plan_baseline
from engine.model import load_rules
from engine.plan import circuit_loads, lift_powered, nonessential_kw, patient_status
from engine.planner import plan_optimal

OUT = Path(__file__).parent


def make_scenario(i: int, gen_factor: float = 1.0, fuel_factor: float = 1.0):
    rng = random.Random(1000 + i)
    faults = tuple(f for f, prob in [("lift_b_off_backup", 0.6), ("isolation_off_backup", 0.5),
                                     ("lift_a_off_backup", 0.15), ("icu_b_off_backup", 0.1)]
                   if rng.random() < prob)
    h = make_hospital(seed=1000 + i, occupancy=rng.uniform(0.7, 1.1),
                      overflow=rng.uniform(0.1, 0.25), faults=faults)
    rules = load_rules()
    demand = float(h.circuits.base_kw.sum()) + 33  # ~33 kW of patient devices
    rated = round(demand * rng.uniform(0.4, 0.7) * gen_factor / 25) * 25
    tank = round(rated * 3.3, -1)
    actual_h = rng.uniform(2, 24)
    h.generator.update({
        "rated_kw": float(rated),
        "tank_l": tank,
        "fuel_l": round(tank * rng.uniform(0.4, 1.0) * fuel_factor),
        "expected_outage_h": round(actual_h * rng.uniform(0.7, 1.3), 1),  # staff's guess
        "refuel_eta_h": round(rng.uniform(6, 18), 1),
    })
    return h, rules, actual_h, faults


def blackout_hours(fuel_l, tank_l, rate, refuel_h, outage_h):
    """Hours the generator is off because the tank is empty, before the outage ends."""
    if rate <= 0:
        return 0.0
    off = 0.0
    run1 = fuel_l / rate
    if run1 < min(refuel_h, outage_h):          # empty before the tanker arrives
        off += min(refuel_h, outage_h) - run1
    if refuel_h < outage_h:                     # tanker fills the tank, generator restarts
        run2 = tank_l / rate
        if refuel_h + run2 < outage_h:
            off += outage_h - (refuel_h + run2)
    return off


def evaluate(h, plan, rules, actual_h):
    g = h.generator
    loads = circuit_loads(h, plan, rules)
    kept_kw = float(loads["load_kw"].sum())
    waste_kw = nonessential_kw(loads, plan)
    rate = fuel.burn_rate(kept_kw, g["rated_kw"])
    off_h = blackout_hours(g["fuel_l"], g["tank_l"], rate, g["refuel_eta_h"], actual_h)
    on_h = actual_h - off_h
    litres = rate * on_h
    pts = patient_status(h, plan, rules)
    ls = pts[pts.life_support].copy()
    ls["unpowered_min"] = ls["powered"].map(lambda pw: off_h * 60 if pw else actual_h * 60)
    ls["harm_min"] = (ls["unpowered_min"] - ls["battery_min"]).clip(lower=0)
    floors = h.room_floor()
    harmed = ls[ls["harm_min"] > 0]
    # Tijuana metric: unpowered from the start, upstairs, and no lift running to move them.
    cut_upstairs = ls[~ls["powered"] & (ls["final_room"].map(floors) > 0)]
    return {
        "method": plan.method,
        "load_kw": kept_kw,
        "nonessential_kw": waste_kw,
        "nonessential_share": waste_kw / kept_kw if kept_kw else 0.0,
        "burn_lph": rate,
        "runtime_per_tank_h": fuel.runtime_h(g["tank_l"], kept_kw, g["rated_kw"]),
        "litres": litres,
        "co2_kg": litres * g["co2_per_l"],
        "diesel_rs": litres * g["diesel_price"],
        "blackout_min": off_h * 60,
        "ls_patients": len(ls),
        "ls_unpowered_at_start": int((~ls["powered"]).sum()),
        "ls_patient_minutes_without_power": float(ls["harm_min"].sum()),
        "emergency_evacuations": len(harmed),
        "stranded_no_lift": 0 if lift_powered(h, plan.kept) else len(cut_upstairs),
        "planned_moves": len(plan.moves),
        "delayed_surgeries": len(plan.delayed_surgeries),
        "solve_s": plan.solve_s,
    }


def run_all(n=50, gen_factor=1.0, fuel_factor=1.0, label="main", log=True):
    rows = []
    for i in range(n):
        h, rules, actual_h, faults = make_scenario(i, gen_factor, fuel_factor)
        g = h.generator
        base = {"scenario": i + 1, "variant": label, "rated_kw": g["rated_kw"],
                "fuel_l": g["fuel_l"], "actual_outage_h": round(actual_h, 1),
                "expected_outage_h": g["expected_outage_h"], "refuel_eta_h": g["refuel_eta_h"],
                "faults": ";".join(faults) or "none"}
        for planner in (plan_baseline, plan_optimal):
            rows.append({**base, **evaluate(h, planner(h, rules), rules, actual_h)})
        if log:
            print(f"\r{label}: scenario {i + 1}/{n}", end="", file=sys.stderr)
    if log:
        print(file=sys.stderr)
    return pd.DataFrame(rows)


def summarize_results(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["ls_patient_minutes_without_power", "ls_unpowered_at_start",
            "emergency_evacuations", "stranded_no_lift", "blackout_min", "load_kw", "burn_lph",
            "runtime_per_tank_h", "litres", "co2_kg", "diesel_rs", "planned_moves"]
    return df.groupby("method")[cols].agg(["sum", "mean"]).round(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip sensitivity runs")
    args = ap.parse_args()
    df = run_all()
    df.to_csv(OUT / "results.csv", index=False)
    summary = summarize_results(df)
    summary.to_csv(OUT / "summary.csv")
    print(summary.T.to_string())
    if not args.quick:
        sens = [run_all(50, gf, ff, f"gen x{gf}, fuel x{ff}")
                for gf, ff in [(0.8, 1.0), (1.2, 1.0), (1.0, 0.8), (1.0, 1.2)]]
        s = pd.concat(sens)
        s.to_csv(OUT / "sensitivity.csv", index=False)
        print(s.groupby(["variant", "method"])[["ls_patient_minutes_without_power",
                                                 "blackout_min", "burn_lph"]].mean().round(1))


if __name__ == "__main__":
    main()
