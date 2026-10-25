"""Pre-outage check: find hidden wiring and data problems BEFORE the power fails.

Each finding has a severity, what was found, and a plain-language fix.
"""
from __future__ import annotations

import pandas as pd

from engine import fuel
from engine.model import Hospital, patient_needs

LOW_BATTERY_MIN = 15


def precheck(h: Hospital, rules: dict) -> pd.DataFrame:
    out = []

    def flag(sev, check, item, detail, fix):
        out.append({"severity": sev, "check": check, "item": item, "detail": detail, "fix": fix})

    c = h.circuits.set_index("id")
    rooms = h.rooms.set_index("id")
    p = patient_needs(h.patients, rules)
    room_circ = h.room_circuit()
    p["circuit_id"] = p["room_id"].map(room_circ)
    g = h.generator

    # 1. data gaps
    for _, r in h.rooms.iterrows():
        if r["circuit_id"] not in c.index:
            flag("High", "Data gap", r["id"], f"Room '{r['name']}' is not mapped to any circuit.",
                 "Trace the room's sockets to a panel and add the circuit id.")
    for _, pt in p[p["room_id"].map(lambda x: x not in rooms.index)].iterrows():
        flag("High", "Data gap", pt["id"], f"Patient is in unknown room '{pt['room_id']}'.",
             "Correct the patient's room in the bed register.")
    for _, pt in p[p["unknown_devices"] != ""].iterrows():
        flag("Medium", "Data gap", pt["id"],
             f"Unknown device type(s): {pt['unknown_devices']} - treated as life support.",
             "Add the device to rules.yaml with its kW and battery time.")

    # 2. life support on circuits not wired to the generator
    off = p[p["life_support"] & p["circuit_id"].map(lambda x: x in c.index and not c.loc[x, "on_backup"])]
    for cid, grp in off.groupby("circuit_id"):
        flag("High", "Life support not on backup", cid,
             f"{len(grp)} life-support patient(s) on '{c.loc[cid, 'name']}', which is NOT on the "
             f"generator: {', '.join(grp['id'])}.",
             "Move these patients to a backup-powered room now, or rewire the circuit to the "
             "emergency panel.")

    # 3. theatres not on backup
    for cid, row in c[(c["kind"] == "OR") & ~c["on_backup"]].iterrows():
        flag("High", "Theatre not on backup", cid, f"{row['name']} is not on the generator.",
             "Rewire to the emergency panel before the next list; do not start long cases there.")

    # 4. lifts / evacuation routes
    lifts = c[c["kind"] == "lift"]
    backup_lifts = lifts[lifts["on_backup"]]
    for cid, row in lifts[~lifts["on_backup"]].iterrows():
        flag("Medium", "Lift not on backup", cid,
             f"{row['name']} stops in an outage.",
             "Connect to the emergency panel or label it 'no backup' at every floor.")
    upper_ls = p[p["life_support"] & p["room_id"].map(lambda r: r in rooms.index and rooms.loc[r, "floor"] > 0)]
    if len(upper_ls) and backup_lifts.empty:
        flag("High", "No powered evacuation route", "lifts",
             f"{len(upper_ls)} life-support patients are above ground floor and no lift is on backup.",
             "Put at least one bed lift on the generator (the Tijuana lesson).")
    elif len(upper_ls) and len(backup_lifts) == 1:
        flag("Low", "Single evacuation lift", backup_lifts.index[0],
             "Only one lift is on backup - a single point of failure.",
             "Plan a stair-carry team and keep a second lift on backup if possible.")

    # 5. circuits above breaker rating at normal load
    dev = p.groupby("circuit_id")["kw"].sum()
    for cid, row in c.iterrows():
        load = row["base_kw"] + dev.get(cid, 0.0)
        if load > row["breaker_kw"]:
            flag("Medium", "Overloaded circuit", cid,
                 f"Normal load {load:.1f} kW is above the {row['breaker_kw']} kW breaker.",
                 "Check with the electrical engineer; spread loads to another circuit.")

    # 6. devices with little or no battery
    weak = p[p["life_support"] & (p["battery_min"] < LOW_BATTERY_MIN)]
    if len(weak):
        flag("Medium", "Little or no device battery", f"{len(weak)} patients",
             f"Life-support devices with under {LOW_BATTERY_MIN} min battery: "
             f"{', '.join(weak['id'].head(12))}{' ...' if len(weak) > 12 else ''}.",
             "Keep manual backups (Ambu bags, O2 cylinders) at these beds; replace batteries.")

    # 7. essential load vs generator and fuel
    in_prog = {room_circ.get(r) for r in h.surgeries.loc[h.surgeries.status == "in_progress", "or_room_id"]}
    ls_circ = set(p.loc[p["life_support"], "circuit_id"])
    essential = c[(c["must_keep"] | c.index.isin(in_prog | ls_circ)) & c["on_backup"]]
    ess_kw = float(essential["base_kw"].sum() + sum(dev.get(i, 0.0) for i in essential.index))
    if ess_kw > g["rated_kw"] * rules["planner"]["capacity_margin"]:
        flag("High", "Generator too small", "generator",
             f"Essential load {ess_kw:.0f} kW exceeds safe generator capacity "
             f"{g['rated_kw'] * rules['planner']['capacity_margin']:.0f} kW.",
             "Arrange a rental generator or consolidate life-support patients onto fewer circuits.")
    rt = fuel.runtime_h(g["fuel_l"], ess_kw, g["rated_kw"])
    if rt < g["refuel_eta_h"]:
        flag("High", "Fuel runs out before refuel", "fuel",
             f"Even at essential load only ({ess_kw:.0f} kW), diesel lasts {rt:.1f} h but the "
             f"tanker needs {g['refuel_eta_h']:.0f} h.",
             "Top up the tank now or agree a faster emergency diesel supply.")

    order = {"High": 0, "Medium": 1, "Low": 2}
    df = pd.DataFrame(out, columns=["severity", "check", "item", "detail", "fix"])
    return df.sort_values("severity", key=lambda s: s.map(order)).reset_index(drop=True)
