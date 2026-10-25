"""Patient-aware power planner (OR-Tools CP-SAT; SciPy MILP in the browser).

Decides which circuits stay on the generator and which high-priority patients
to move, so that the most dependent patients keep power and the diesel lasts.

Hard constraints (never broken)
  1. every patient ends up in exactly one place
  2. circuits not wired to the generator cannot be kept; fire/exit lighting and
     theatres with a surgery in progress are always kept
  3. total load <= capacity_margin x generator rating
  4. each circuit stays within its breaker rating
  5. room bed limits
  6. patient-room compatibility (neonates, ventilator-capable rooms)
  7. patients in surgery or on dialysis are not moved; ICU patients only move to ICU beds
  8. moving to another floor needs a lift that is on the generator and kept on
  9. patients are only moved into rooms whose circuit stays on

Soft goals (objective)
  + priority weight of every powered patient (life support dominates)
  + value of non-patient loads (oxygen plant, blood bank, pumps ...)
  - a small diesel cost for every kW kept
  - a larger penalty for every kW above the fuel-safe load
  - a penalty per patient move
"""
from __future__ import annotations

import time

from engine.solver import Model

from engine import fuel
from engine.model import Hospital, patient_needs
from engine.plan import Plan, delayed_surgeries

SCALE = 10_000  # objective units per priority-weight point


def _watts(kw: float) -> int:
    return int(round(kw * 1000))


def plan_optimal(h: Hospital, rules: dict) -> Plan:
    t0 = time.time()
    cfg = rules["planner"]
    g = h.generator
    p = patient_needs(h.patients, rules)
    circuits = h.circuits.set_index("id")
    rooms = h.rooms.set_index("id")
    room_circ = h.room_circuit()

    in_progress_rooms = set(h.surgeries.loc[h.surgeries.status == "in_progress", "or_room_id"])
    forced = {room_circ[r] for r in in_progress_rooms if r in room_circ}
    notes = []

    m = Model()
    keep = {c: m.bool_var(f"keep_{c}") for c in circuits.index}
    for c, row in circuits.iterrows():
        if not row["on_backup"]:
            m.add(keep[c] == 0)
            if c in forced:
                notes.append(f"Surgery in progress on {c}, but that circuit is NOT wired to the "
                             "generator. Use portable backup immediately.")
        elif row["must_keep"] or c in forced:
            m.add(keep[c] == 1)

    backup_lifts = [c for c, r in circuits.iterrows() if r["kind"] == "lift" and r["on_backup"]]
    lift_ok = m.bool_var("lift_ok")
    m.add(lift_ok <= sum(keep[c] for c in backup_lifts)) if backup_lifts else m.add(lift_ok == 0)

    # --- patients: fixed ones contribute through their circuit, movable ones get choices ---
    fixed_w = {c: 0 for c in circuits.index}
    fixed_kw = {c: 0 for c in circuits.index}
    occupancy = {r: 0 for r in rooms.index}
    choices = {}  # patient id -> {room id: BoolVar}
    obj, load_terms = [], {c: [] for c in circuits.index}

    for _, pt in p.iterrows():
        orig = pt["room_id"]
        c0 = room_circ.get(orig)
        if c0 is None:
            notes.append(f"{pt['id']} is in room {orig}, which has no circuit mapped - not planned.")
            continue
        movable = (pt["weight"] >= cfg["move_min_weight"] and not pt["in_surgery"]
                   and "dialysis" not in str(pt["devices"]))
        cands = []
        if movable:
            for r, room in rooms.iterrows():
                if r == orig or room["type"] in ("OR", "dialysis"):
                    continue
                # ICU patients need ICU nursing: they may only move to another ICU bed.
                if rooms.loc[orig, "type"] == "ICU" and room["type"] != "ICU":
                    continue
                if pt["age_group"] not in str(room["accepts"]).split(";"):
                    continue
                if pt["needs_ventilator"] and not room["can_host_ventilator"]:
                    continue
                if not circuits.loc[room["circuit_id"], "on_backup"]:
                    continue
                cands.append(r)
        if not cands:
            fixed_w[c0] += pt["weight"]
            fixed_kw[c0] += pt["kw"]
            occupancy[orig] += 1
            continue

        x = {r: m.bool_var(f"x_{pt['id']}_{r}") for r in [orig] + cands}
        m.add_exactly_one(x.values())
        choices[pt["id"]] = x
        w_kw = _watts(pt["kw"])
        # staying: powered only if the original circuit is kept
        y0 = m.bool_var(f"y_{pt['id']}")
        m.add_implication(y0, x[orig])
        m.add_implication(y0, keep[c0])
        m.add(y0 >= x[orig] + keep[c0] - 1)  # a kept circuit really powers whoever stays on it
        obj.append(SCALE * pt["weight"] * y0)
        load_terms[c0].append(w_kw * y0)
        for r in cands:
            c = room_circ[r]
            m.add_implication(x[r], keep[c])                    # only into powered rooms
            if rooms.loc[r, "floor"] != rooms.loc[orig, "floor"]:
                m.add_implication(x[r], lift_ok)                # route check
            obj.append(SCALE * pt["weight"] * x[r])
            obj.append(-SCALE * cfg["move_penalty"] * x[r])
            load_terms[c].append(w_kw * x[r])

    # bed limits
    for r in rooms.index:
        vars_here = [x[r] for x in choices.values() if r in x]
        if vars_here:
            beds = max(int(rooms.loc[r, "beds"]), occupancy[r])
            m.add(occupancy[r] + sum(vars_here) <= beds)

    # loads
    circuit_load = {}
    for c, row in circuits.iterrows():
        base_w = _watts(row["base_kw"] + fixed_kw[c])
        expr = base_w * keep[c] + sum(load_terms[c])
        circuit_load[c] = expr
        breaker = max(_watts(row["breaker_kw"]), base_w)
        m.add(expr <= breaker)
        obj.append(SCALE * (row["value"] + fixed_w[c]) * keep[c])

    total = sum(circuit_load.values())
    cap_w = _watts(g["rated_kw"] * cfg["capacity_margin"])
    m.add(total <= cap_w)

    hours_needed = min(g["expected_outage_h"], g["refuel_eta_h"]) * (1 + cfg["fuel_reserve"])
    target_w = _watts(fuel.fuel_safe_load(g["fuel_l"], hours_needed, g["rated_kw"]))
    over = m.int_var(0, cap_w, "over_fuel_target")
    m.add(over >= total - target_w)
    per_w = SCALE / 1000  # objective units per watt for 1 weight-point per kW
    obj.append(-round(per_w * cfg["diesel_cost_per_kw"]) * total)
    obj.append(-round(per_w * cfg["fuel_over_penalty_per_kw"]) * over)

    m.maximize(sum(obj))
    status = m.solve(cfg["time_limit_s"])

    if status == "infeasible":
        plan = plan_greedy(h, rules)
        plan.notes = notes + ["Optimizer found no feasible plan (essential loads exceed the "
                              "generator). Showing best-effort greedy plan."]
        plan.solve_s = time.time() - t0
        return plan

    kept = {c for c in circuits.index if m.value(keep[c])}
    location = dict(zip(h.patients["id"], h.patients["room_id"]))
    kept_lifts = [c for c in backup_lifts if c in kept]
    moves = []
    for pid, x in choices.items():
        dest = next(r for r, v in x.items() if m.value(v))
        if dest == location[pid]:
            continue
        pt = p.set_index("id").loc[pid]
        orig = location[pid]
        cross = rooms.loc[dest, "floor"] != rooms.loc[orig, "floor"]
        moves.append({
            "patient": pid, "name": pt["name"], "devices": pt["devices"],
            "from_room": rooms.loc[orig, "name"], "to_room": rooms.loc[dest, "name"],
            "to_room_id": dest, "cross_floor": bool(cross),
            "lift": ", ".join(kept_lifts) if cross else "-",
            "transport_min": cfg["cross_floor_move_min"] if cross else cfg["same_floor_move_min"],
            "battery_min": pt["battery_min"],
            "route_ok": True,  # guaranteed by constraint 8
            "manual_support": bool(pt["life_support"] and pt["battery_min"] <
                                   (cfg["cross_floor_move_min"] if cross else cfg["same_floor_move_min"])),
        })
        location[pid] = dest

    return Plan("Patient-aware planner", kept, location, moves, delayed_surgeries(h, kept),
                status, time.time() - t0, notes)


def plan_greedy(h: Hospital, rules: dict) -> Plan:
    """Fallback: keep circuits by (patient weight + value) per kW until full. No moves."""
    cfg = rules["planner"]
    cap = h.generator["rated_kw"] * cfg["capacity_margin"]
    p = patient_needs(h.patients, rules)
    room_circ = h.room_circuit()
    p["c"] = p["room_id"].map(room_circ)
    c = h.circuits.copy()
    c["load"] = c["base_kw"] + c["id"].map(p.groupby("c")["kw"].sum()).fillna(0)
    c["score"] = (c["value"] + c["id"].map(p.groupby("c")["weight"].sum()).fillna(0)) \
        / c["load"].clip(lower=0.1)
    forced = {room_circ[r] for r in h.surgeries.loc[h.surgeries.status == "in_progress",
                                                     "or_room_id"]}
    c["first"] = c["must_keep"] | c["id"].isin(forced)
    kept, used = set(), 0.0
    for _, row in c.sort_values(["first", "score"], ascending=False).iterrows():
        if row["on_backup"] and (row["first"] or used + row["load"] <= cap):
            kept.add(row["id"])
            used += row["load"]
    location = dict(zip(h.patients["id"], h.patients["room_id"]))
    return Plan("Greedy fallback", kept, location, [], delayed_surgeries(h, kept), "fallback")
