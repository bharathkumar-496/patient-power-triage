"""A power plan (which circuits stay on, where patients end up) and its summary.

Both the fixed-list baseline and the optimizer return a Plan, so the dashboard
and the simulation treat them the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from engine import fuel
from engine.model import Hospital, patient_needs


@dataclass
class Plan:
    method: str
    kept: set                      # circuit ids that stay on the generator
    location: dict                 # patient id -> room id after any moves
    moves: list = field(default_factory=list)
    delayed_surgeries: list = field(default_factory=list)
    status: str = "ok"
    solve_s: float = 0.0
    notes: list = field(default_factory=list)


def circuit_loads(h: Hospital, plan: Plan, rules: dict) -> pd.DataFrame:
    """Load per circuit after the plan (0 if the circuit is cut)."""
    p = patient_needs(h.patients, rules)
    room_circ = h.room_circuit()
    p["circuit_id"] = p["id"].map(plan.location).map(room_circ)
    dev_kw = p.groupby("circuit_id")["kw"].sum()
    c = h.circuits.copy()
    c["device_kw"] = c["id"].map(dev_kw).fillna(0.0)
    c["kept"] = c["id"].isin(plan.kept)
    c["load_kw"] = (c["base_kw"] + c["device_kw"]).where(c["kept"], 0.0)
    c["patients"] = c["id"].map(p.groupby("circuit_id")["id"].count()).fillna(0).astype(int)
    c["life_support_patients"] = c["id"].map(
        p[p.life_support].groupby("circuit_id")["id"].count()).fillna(0).astype(int)
    return c


def patient_status(h: Hospital, plan: Plan, rules: dict) -> pd.DataFrame:
    p = patient_needs(h.patients, rules)
    room_circ = h.room_circuit()
    p["final_room"] = p["id"].map(plan.location)
    p["circuit_id"] = p["final_room"].map(room_circ)
    p["powered"] = p["circuit_id"].isin(plan.kept)
    p["moved"] = p["final_room"] != p["room_id"]
    return p


def nonessential_kw(loads: pd.DataFrame, plan: Plan) -> float:
    """Generator load spent on circuits with no patients and little value
    (empty theatres, offices, corridors, kitchen, CT...). Lifts count unless
    the plan uses them to move patients between floors."""
    used_lift = any(m["cross_floor"] for m in plan.moves)
    k = loads[loads.kept & ~loads.must_keep & (loads.patients == 0) & (loads.value <= 10)]
    if used_lift:
        k = k[k.kind != "lift"]
    return float(k["load_kw"].sum())


def summarize(h: Hospital, plan: Plan, rules: dict) -> dict:
    g = h.generator
    loads = circuit_loads(h, plan, rules)
    pts = patient_status(h, plan, rules)
    demand = float((loads["base_kw"] + loads["device_kw"]).sum())
    kept_kw = float(loads["load_kw"].sum())
    rate = fuel.burn_rate(kept_kw, g["rated_kw"])
    runtime = fuel.runtime_h(g["fuel_l"], kept_kw, g["rated_kw"])
    ls = pts[pts.life_support]
    return {
        "method": plan.method,
        "demand_kw": demand,
        "capacity_kw": g["rated_kw"],
        "kept_kw": kept_kw,
        "cut_kw": demand - kept_kw,
        "nonessential_kw": nonessential_kw(loads, plan),
        "load_pct": 100 * kept_kw / g["rated_kw"],
        "burn_lph": rate,
        "runtime_h": runtime,
        "hours_needed": min(g["expected_outage_h"], g["refuel_eta_h"]),
        "life_support_total": int(len(ls)),
        "life_support_powered": int(ls["powered"].sum()),
        "patients_powered": int(pts["powered"].sum()),
        "patients_total": int(len(pts)),
        "moves": len(plan.moves),
        "delayed_surgeries": len(plan.delayed_surgeries),
        "circuits_kept": len(plan.kept),
        "circuits_total": len(h.circuits),
        "status": plan.status,
        "solve_s": plan.solve_s,
    }


def delayed_surgeries(h: Hospital, kept: set) -> list:
    room_circ = h.room_circuit()
    out = []
    for _, s in h.surgeries.iterrows():
        if s["status"] == "scheduled" and room_circ.get(s["or_room_id"]) not in kept:
            out.append({"surgery": s["id"], "room": s["or_room_id"], "procedure": s["procedure"],
                        "reason": "Theatre circuit cut to save generator capacity"})
    return out


def lift_powered(h: Hospital, kept: set) -> bool:
    lifts = h.circuits[(h.circuits.kind == "lift") & h.circuits.on_backup]
    return any(c in kept for c in lifts["id"])
