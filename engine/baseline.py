"""Today's practice: a fixed department shed list.

Circuits are kept in a fixed department order until the generator is full.
It knows nothing about which patients are where, never moves anyone, and does
not think about fuel. This is what we compare our planner against.
"""
from __future__ import annotations

from engine.model import Hospital, patient_needs
from engine.plan import Plan, delayed_surgeries


def plan_baseline(h: Hospital, rules: dict) -> Plan:
    cap = h.generator["rated_kw"] * rules["planner"]["capacity_margin"]
    order = {k: i for i, k in enumerate(rules["baseline_order"])}

    p = patient_needs(h.patients, rules)
    room_circ = h.room_circuit()
    dev_kw = p.assign(c=p["room_id"].map(room_circ)).groupby("c")["kw"].sum()

    in_progress_rooms = set(h.surgeries.loc[h.surgeries.status == "in_progress", "or_room_id"])
    forced = {room_circ[r] for r in in_progress_rooms if r in room_circ}

    c = h.circuits.copy()
    c["load"] = c["base_kw"] + c["id"].map(dev_kw).fillna(0)
    c["rank"] = c["kind"].map(order).fillna(len(order))
    c["first"] = c["must_keep"] | c["id"].isin(forced)
    c = c.sort_values(["first", "rank", "id"], ascending=[False, True, True])

    kept, used = set(), 0.0
    for _, row in c.iterrows():
        if not row["on_backup"]:
            continue  # not wired to the generator: cannot be kept
        if used + row["load"] <= cap:
            kept.add(row["id"])
            used += row["load"]

    location = dict(zip(h.patients["id"], h.patients["room_id"]))
    return Plan("Fixed list (today)", kept, location, [], delayed_surgeries(h, kept))
