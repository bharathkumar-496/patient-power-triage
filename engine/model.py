"""Hospital data model: the five tables plus generator settings.

Everything is plain pandas DataFrames so the same data can come from the fake
hospital generator, an Excel upload, or manual edits in the dashboard.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "rules.yaml"

CIRCUIT_COLS = ["id", "name", "panel", "floor", "kind", "base_kw", "breaker_kw",
                "on_backup", "must_keep", "value"]
ROOM_COLS = ["id", "name", "floor", "type", "beds", "circuit_id", "accepts",
             "can_host_ventilator"]
PATIENT_COLS = ["id", "name", "age_group", "room_id", "devices", "battery_min",
                "in_surgery"]
SURGERY_COLS = ["id", "or_room_id", "status", "patient_id", "procedure",
                "expected_end_min"]
GENERATOR_DEFAULTS = {
    "rated_kw": 300.0,         # generator nameplate rating
    "fuel_l": 800.0,           # diesel in the tank now
    "tank_l": 1000.0,          # tank size
    "expected_outage_h": 8.0,  # staff's best guess of outage length
    "refuel_eta_h": 12.0,      # hours until a diesel tanker can arrive
    "diesel_price": 90.0,      # Rs per litre (assumed)
    "co2_per_l": 2.68,         # kg CO2 per litre of diesel burned
}


def load_rules(path: Path = RULES_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


@dataclass
class Hospital:
    circuits: pd.DataFrame
    rooms: pd.DataFrame
    patients: pd.DataFrame
    surgeries: pd.DataFrame
    generator: dict = field(default_factory=lambda: dict(GENERATOR_DEFAULTS))

    def copy(self) -> "Hospital":
        return Hospital(self.circuits.copy(), self.rooms.copy(), self.patients.copy(),
                        self.surgeries.copy(), copy.deepcopy(self.generator))

    # ---------- lookups ----------
    def room_circuit(self) -> dict:
        return dict(zip(self.rooms["id"], self.rooms["circuit_id"]))

    def room_floor(self) -> dict:
        return dict(zip(self.rooms["id"], self.rooms["floor"]))


def device_list(devices) -> list[str]:
    """'ventilator;monitor' -> ['ventilator', 'monitor']; blank -> ['none']."""
    if devices is None or (isinstance(devices, float) and pd.isna(devices)):
        return ["none"]
    items = [d.strip() for d in str(devices).replace(",", ";").split(";") if d.strip()]
    return items or ["none"]


def patient_needs(patients: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """Add kw, weight, life_support, battery_min and needs_ventilator per patient.

    weight = highest-priority device; kw = sum of device draws;
    battery = shortest internal battery among life-support devices.
    """
    catalogue = rules["devices"]
    unknown = rules["unknown_device"]
    rows = []
    for _, p in patients.iterrows():
        devs = device_list(p.get("devices"))
        specs = [catalogue.get(d, unknown) for d in devs]
        unknown_types = [d for d in devs if d not in catalogue]
        ls_specs = [s for s in specs if s["life_support"]]
        battery = min((s["battery_min"] for s in ls_specs), default=0)
        override = p.get("battery_min")
        if override is not None and not pd.isna(override):
            battery = float(override)
        rows.append({
            "kw": sum(s["kw"] for s in specs),
            "weight": max(s["weight"] for s in specs),
            "life_support": bool(ls_specs),
            "battery_min": battery,
            "needs_ventilator": "ventilator" in devs,
            "unknown_devices": ";".join(unknown_types),
        })
    extra = pd.DataFrame(rows, index=patients.index)
    out = patients.drop(columns=["battery_min"], errors="ignore").join(extra)
    out["in_surgery"] = out["in_surgery"].fillna(False).astype(bool)
    return out


# ---------- Excel in / out ----------

def to_excel_bytes(h: Hospital) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        h.circuits.to_excel(xw, sheet_name="circuits", index=False)
        h.rooms.to_excel(xw, sheet_name="rooms", index=False)
        h.patients.to_excel(xw, sheet_name="patients", index=False)
        h.surgeries.to_excel(xw, sheet_name="surgeries", index=False)
        pd.DataFrame({"key": list(h.generator), "value": list(h.generator.values())}) \
            .to_excel(xw, sheet_name="generator", index=False)
    return buf.getvalue()


def from_excel(src) -> Hospital:
    """Read an uploaded workbook. Missing optional columns get safe defaults."""
    xl = pd.read_excel(src, sheet_name=None)
    missing = {"circuits", "rooms", "patients"} - set(xl)
    if missing:
        raise ValueError(f"Workbook is missing sheet(s): {', '.join(sorted(missing))}")

    def ensure(df, cols, defaults):
        for c in cols:
            if c not in df.columns:
                df[c] = defaults.get(c)
        return df[cols]

    circuits = ensure(xl["circuits"], CIRCUIT_COLS,
                      {"panel": "", "on_backup": True, "must_keep": False, "value": 1,
                       "breaker_kw": 1e6})
    rooms = ensure(xl["rooms"], ROOM_COLS, {"accepts": "adult;child;neonate",
                                            "can_host_ventilator": True})
    patients = ensure(xl["patients"], PATIENT_COLS,
                      {"name": "", "age_group": "adult", "battery_min": None,
                       "in_surgery": False})
    surgeries = ensure(xl.get("surgeries", pd.DataFrame()), SURGERY_COLS, {})
    gen = dict(GENERATOR_DEFAULTS)
    if "generator" in xl:
        g = xl["generator"]
        gen.update({str(k): float(v) for k, v in zip(g["key"], g["value"])})
    for col in ("on_backup", "must_keep"):
        circuits[col] = circuits[col].fillna(False).astype(bool)
    rooms["can_host_ventilator"] = rooms["can_host_ventilator"].fillna(True).astype(bool)
    return Hospital(circuits, rooms, patients, surgeries, gen)
