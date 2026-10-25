"""Generate a FAKE 200-bed government district hospital.

All names and records are synthetic. Loads are typical values (assumed) - see
docs/ASSUMPTIONS.md. Run directly to write data/hospital.xlsx:

    .venv/bin/python -m data.generate
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

from engine.model import GENERATOR_DEFAULTS, Hospital, to_excel_bytes

# id, name, panel, floor, kind, base_kw, breaker_kw, on_backup, must_keep, value
CIRCUITS = [
    ("C-FIRE",  "Fire alarm & exit lighting",      "EP-G", 0, "fire",       4,  10, True, True,  0),
    ("C-ER",    "Emergency / casualty",            "EP-G", 0, "ER",        18,  40, True, False, 30),
    ("C-OPD",   "OPD block",                       "DB-G", 0, "opd",       20,  40, True, False, 3),
    ("C-ADM",   "Admin offices (AC)",              "DB-G", 0, "admin",     30,  50, True, False, 1),
    ("C-KIT",   "Kitchen",                         "DB-G", 0, "kitchen",   35,  50, True, False, 4),
    ("C-LAU",   "Laundry",                         "DB-G", 0, "laundry",   40,  60, True, False, 1),
    ("C-CT",    "CT scan & X-ray",                 "DB-G", 0, "radiology", 60, 100, True, False, 6),
    ("C-MRI",   "MRI chiller",                     "DB-G", 0, "radiology", 25,  40, True, False, 20),
    ("C-LAB",   "Laboratory analysers",            "EP-G", 0, "lab",       20,  40, True, False, 15),
    ("C-BB",    "Blood bank & pharmacy cold chain","EP-G", 0, "cold_chain", 6,  16, True, False, 40),
    ("C-DIA",   "Dialysis unit (RO plant)",        "EP-G", 0, "dialysis",  12,  40, True, False, 5),
    ("C-PMP",   "Water pumps",                     "EP-G", 0, "pumps",     15,  30, True, False, 25),
    ("C-O2",    "PSA oxygen plant",                "EP-G", 0, "oxygen",    30,  50, True, False, 60),
    ("C-LIFTA", "Bed lift A",                      "EP-G", 0, "lift",      15,  25, True, False, 0),
    ("C-LIFTB", "Bed lift B",                      "DB-G", 0, "lift",      15,  25, True, False, 0),
    ("C-OR1",   "Operating theatre 1",             "EP-1", 1, "OR",        22,  40, True, False, 10),
    ("C-OR2",   "Operating theatre 2",             "EP-1", 1, "OR",        22,  40, True, False, 10),
    ("C-OR3",   "Operating theatre 3",             "EP-1", 1, "OR",        22,  40, True, False, 10),
    ("C-OR4",   "Operating theatre 4",             "EP-1", 1, "OR",        22,  40, True, False, 10),
    ("C-ICUA",  "ICU bay A",                       "EP-1", 1, "ICU",       14,  40, True, False, 5),
    ("C-ICUB",  "ICU bay B",                       "EP-1", 1, "ICU",       14,  40, True, False, 5),
    ("C-NICU",  "NICU",                            "EP-1", 1, "NICU",      10,  30, True, False, 5),
    ("C-POP",   "Post-op ward",                    "EP-1", 1, "ward",       8,  25, True, False, 2),
    ("C-F1C",   "Floor 1 corridor & nurse station AC", "DB-1", 1, "corridor", 18, 30, True, False, 2),
    ("C-WMM",   "Male medical ward",               "DB-2", 2, "ward",       8,  25, True, False, 2),
    ("C-WFM",   "Female medical ward",             "DB-2", 2, "ward",       8,  25, True, False, 2),
    ("C-WSU",   "Surgical ward",                   "DB-2", 2, "ward",       8,  25, True, False, 2),
    ("C-F2C",   "Floor 2 corridor AC",             "DB-2", 2, "corridor",  15,  30, True, False, 1),
    ("C-WPD",   "Paediatric ward",                 "DB-3", 3, "ward",       8,  25, True, False, 2),
    ("C-WMT",   "Maternity ward",                  "DB-3", 3, "ward",       8,  25, True, False, 2),
    ("C-WOR",   "Orthopaedic ward",                "DB-3", 3, "ward",       8,  25, True, False, 2),
    ("C-WIS",   "Isolation ward",                  "DB-3", 3, "ward",       6,  20, True, False, 2),
    ("C-F3C",   "Floor 3 corridor AC",             "DB-3", 3, "corridor",  15,  30, True, False, 1),
]

# id, name, floor, type, beds, circuit_id, accepts, can_host_ventilator
ROOMS = [
    ("R-ER",   "Casualty",           0, "ER",       10, "C-ER",   "adult;child;neonate", True),
    ("R-DIA",  "Dialysis unit",      0, "dialysis",  6, "C-DIA",  "adult;child",         False),
    ("R-OR1",  "OT 1",               1, "OR",        1, "C-OR1",  "adult;child;neonate", True),
    ("R-OR2",  "OT 2",               1, "OR",        1, "C-OR2",  "adult;child;neonate", True),
    ("R-OR3",  "OT 3",               1, "OR",        1, "C-OR3",  "adult;child;neonate", True),
    ("R-OR4",  "OT 4",               1, "OR",        1, "C-OR4",  "adult;child;neonate", True),
    ("R-ICUA", "ICU bay A",          1, "ICU",       6, "C-ICUA", "adult;child",         True),
    ("R-ICUB", "ICU bay B",          1, "ICU",       6, "C-ICUB", "adult;child",         True),
    ("R-NICU", "NICU",               1, "NICU",     10, "C-NICU", "neonate",             True),
    ("R-POP",  "Post-op ward",       1, "ward",     10, "C-POP",  "adult;child",         True),
    ("R-WMM",  "Male medical ward",  2, "ward",     24, "C-WMM",  "adult",               True),
    ("R-WFM",  "Female medical ward",2, "ward",     24, "C-WFM",  "adult",               True),
    ("R-WSU",  "Surgical ward",      2, "ward",     24, "C-WSU",  "adult",               True),
    ("R-WPD",  "Paediatric ward",    3, "ward",     24, "C-WPD",  "child",               True),
    ("R-WMT",  "Maternity ward",     3, "ward",     24, "C-WMT",  "adult;neonate",       False),
    ("R-WOR",  "Orthopaedic ward",   3, "ward",     24, "C-WOR",  "adult",               True),
    ("R-WIS",  "Isolation ward",     3, "ward",      8, "C-WIS",  "adult;child",         True),
]

FIRST = ["Aarav", "Priya", "Ravi", "Lakshmi", "Arjun", "Meena", "Karthik", "Divya", "Suresh",
         "Anitha", "Vijay", "Kavya", "Manoj", "Deepa", "Rahul", "Sneha", "Ganesh", "Pooja",
         "Imran", "Fatima", "Joseph", "Mary", "Harish", "Revathi", "Sanjay", "Nandini"]
LAST = ["Kumar", "Sharma", "Reddy", "Iyer", "Nair", "Patel", "Das", "Singh", "Rao", "Khan",
        "Pillai", "Gupta", "Menon", "Shetty", "Joshi", "Verma"]
PROCEDURES = ["Caesarean section", "Laparotomy", "Appendicectomy", "Hip fixation",
              "Cholecystectomy", "Hernia repair", "Craniotomy"]

# Devices by room type: (device, probability).
DEVICE_MIX = {
    "ICU":      [("ventilator", 0.7), ("monitor", 1.0), ("inotrope_pump", 0.4), ("suction", 0.3)],
    "NICU":     [("incubator", 1.0), ("ventilator", 0.2), ("monitor", 0.8)],
    "ER":       [("monitor", 0.6), ("ventilator", 0.1), ("o2_concentrator", 0.2)],
    "dialysis": [("dialysis", 1.0), ("monitor", 0.5)],
    "ward":     [("o2_concentrator", 0.10), ("monitor", 0.10), ("suction", 0.03)],
}


def make_hospital(seed: int = 7, occupancy: float = 0.9, overflow: float = 0.2,
                  surgery_prob: float = 0.5, faults: tuple = ("lift_b_off_backup",
                                                              "isolation_off_backup"),
                  generator: dict | None = None) -> Hospital:
    """Build the fake hospital.

    occupancy: share of ward beds filled (can exceed 1 - extra floor beds are ignored).
    overflow:  ventilated patients placed in general wards, as a share of ICU beds
               (ICU-full overflow, common in government hospitals).
    faults:    real-world wiring problems to inject (found by the pre-outage check).
    """
    rng = random.Random(seed)
    circuits = pd.DataFrame(CIRCUITS, columns=["id", "name", "panel", "floor", "kind",
                                               "base_kw", "breaker_kw", "on_backup",
                                               "must_keep", "value"])
    rooms = pd.DataFrame(ROOMS, columns=["id", "name", "floor", "type", "beds", "circuit_id",
                                         "accepts", "can_host_ventilator"])
    if "lift_b_off_backup" in faults:
        circuits.loc[circuits.id == "C-LIFTB", "on_backup"] = False
    if "lift_a_off_backup" in faults:
        circuits.loc[circuits.id == "C-LIFTA", "on_backup"] = False
    if "isolation_off_backup" in faults:
        circuits.loc[circuits.id == "C-WIS", "on_backup"] = False
    if "icu_b_off_backup" in faults:  # a mis-mapped panel: ICU bay B fed from normal supply
        circuits.loc[circuits.id == "C-ICUB", "on_backup"] = False

    patients, surgeries = [], []
    counter = iter(range(1, 10_000))

    def new_patient(room_id, age_group, devices, in_surgery=False, battery=None):
        pid = f"P{next(counter):03d}"
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}" if age_group != "neonate" \
            else f"Baby of {rng.choice(FIRST)}"
        patients.append({"id": pid, "name": name, "age_group": age_group, "room_id": room_id,
                         "devices": ";".join(devices) if devices else "none",
                         "battery_min": battery, "in_surgery": in_surgery})
        return pid

    def pick_devices(room_type):
        devs = [d for d, p in DEVICE_MIX.get(room_type, []) if rng.random() < p]
        return devs

    def vent_battery():
        # About 30% of ventilators in older government stock have no working battery (assumed).
        return 0 if rng.random() < 0.3 else rng.choice([30, 45, 60])

    for _, r in rooms.iterrows():
        if r.type == "OR":
            continue
        fill = r.beds if r.type in ("ICU", "NICU") else round(r.beds * min(occupancy, 1.0))
        fill = min(fill, r.beds)
        for _ in range(fill):
            if r.type == "NICU" or (r.id == "R-WMT" and rng.random() < 0.3):
                age = "neonate"
                devs = pick_devices("NICU") if r.type == "NICU" else []
            elif r.id == "R-WPD":
                age = "child"
                devs = pick_devices("ward")
            else:
                age = "adult" if rng.random() < 0.9 or "child" not in r.accepts else "child"
                devs = pick_devices(r.type)
            battery = vent_battery() if "ventilator" in devs else None
            new_patient(r.id, age, devs, battery=battery)

    # ICU overflow: ventilated patients sitting in general wards.
    n_overflow = round(overflow * 12)
    # Isolation ward comes early so an off-backup ward really has someone at risk.
    ward_rooms = ["R-WIS", "R-WMM", "R-WFM", "R-WSU", "R-WOR", "R-POP"]
    for i in range(n_overflow):
        room = ward_rooms[i % len(ward_rooms)] if i < len(ward_rooms) else rng.choice(ward_rooms)
        # replace an existing no-device patient so bed counts stay valid
        idx = [k for k, p in enumerate(patients) if p["room_id"] == room and p["devices"] == "none"]
        devs = ["ventilator", "monitor"]
        if idx:
            k = rng.choice(idx)
            patients[k]["devices"] = ";".join(devs)
            patients[k]["battery_min"] = vent_battery()
        else:
            new_patient(room, "adult", devs, battery=vent_battery())

    # Operating theatres: some surgeries in progress, others waiting.
    for n in range(1, 5):
        room = f"R-OR{n}"
        proc = rng.choice(PROCEDURES)
        if rng.random() < surgery_prob:
            pid = new_patient(room, "adult", ["ventilator", "monitor", "suction"],
                              in_surgery=True, battery=vent_battery())
            surgeries.append({"id": f"S{n}", "or_room_id": room, "status": "in_progress",
                              "patient_id": pid, "procedure": proc,
                              "expected_end_min": rng.choice([30, 60, 90, 120])})
        else:
            surgeries.append({"id": f"S{n}", "or_room_id": room, "status": "scheduled",
                              "patient_id": None, "procedure": proc,
                              "expected_end_min": rng.choice([120, 180, 240])})

    gen = dict(GENERATOR_DEFAULTS)
    if generator:
        gen.update(generator)
    return Hospital(circuits, rooms, pd.DataFrame(patients), pd.DataFrame(surgeries), gen)


if __name__ == "__main__":
    h = make_hospital()
    out = Path(__file__).parent / "hospital.xlsx"
    out.write_bytes(to_excel_bytes(h))
    print(f"Wrote {out} - {len(h.patients)} patients, {len(h.circuits)} circuits")
