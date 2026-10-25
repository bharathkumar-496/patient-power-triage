"""Checks that the planner never breaks a hard constraint, plus fuel and pre-check tests.

    .venv/bin/python -m pytest -q
"""
import math

import pytest

from data.generate import make_hospital
from engine import fuel
from engine.baseline import plan_baseline
from engine.model import from_excel, load_rules, patient_needs, to_excel_bytes
from engine.plan import circuit_loads, lift_powered, patient_status
from engine.planner import plan_optimal
from engine.precheck import precheck
from engine.whatif import apply_whatif

RULES = load_rules()

SCENARIOS = [
    dict(seed=7, generator={"rated_kw": 300, "fuel_l": 800}),
    dict(seed=11, generator={"rated_kw": 200, "fuel_l": 300}, overflow=0.4),
    dict(seed=21, generator={"rated_kw": 150, "fuel_l": 600},
         faults=("lift_b_off_backup", "isolation_off_backup", "icu_b_off_backup")),
    dict(seed=33, generator={"rated_kw": 400, "fuel_l": 200}, occupancy=1.1),
]


@pytest.fixture(params=SCENARIOS, ids=lambda s: f"seed{s['seed']}")
def case(request):
    h = make_hospital(**request.param)
    return h, plan_optimal(h, RULES)


# ---------- hard constraints ----------

def test_capacity_and_breakers(case):
    h, plan = case
    loads = circuit_loads(h, plan, RULES)
    assert loads.load_kw.sum() <= h.generator["rated_kw"] * RULES["planner"]["capacity_margin"] + 1e-3
    kept = loads[loads.kept]
    assert (kept.load_kw <= kept[["breaker_kw", "base_kw"]].max(axis=1) + 1e-3).all()


def test_non_backup_never_kept_and_must_keep_kept(case):
    h, plan = case
    c = h.circuits.set_index("id")
    assert not any(not c.loc[k, "on_backup"] for k in plan.kept)
    assert set(c[c.must_keep & c.on_backup].index) <= plan.kept


def test_surgery_in_progress_always_powered(case):
    h, plan = case
    rc = h.room_circuit()
    for r in h.surgeries.loc[h.surgeries.status == "in_progress", "or_room_id"]:
        if h.circuits.set_index("id").loc[rc[r], "on_backup"]:
            assert rc[r] in plan.kept


def test_beds_compatibility_and_routes(case):
    h, plan = case
    pts = patient_status(h, plan, RULES)
    rooms = h.rooms.set_index("id")
    before = h.patients.groupby("room_id").size()
    after = pts.groupby("final_room").size()
    for r, n in after.items():
        assert n <= max(rooms.loc[r, "beds"], before.get(r, 0))
    for m in plan.moves:
        p = pts.set_index("id").loc[m["patient"]]
        dest = rooms.loc[m["to_room_id"]]
        assert p["age_group"] in dest["accepts"].split(";")
        assert not p["in_surgery"]
        assert dest["circuit_id"] in plan.kept                    # moved into a powered room
        if p["needs_ventilator"]:
            assert dest["can_host_ventilator"]
        if m["cross_floor"]:
            assert lift_powered(h, plan.kept)                     # route check


def test_planner_never_worse_than_baseline_on_life_support(case):
    h, plan = case
    ls = lambda pl: patient_status(h, pl, RULES).query("life_support").powered.sum()
    assert ls(plan) >= ls(plan_baseline(h, RULES))


def test_solves_fast(case):
    _, plan = case
    assert plan.solve_s < 5


# ---------- sanity scenarios ----------

def test_big_generator_cuts_nothing_needed():
    h = make_hospital(generator={"rated_kw": 2000, "fuel_l": 20000, "tank_l": 20000})
    plan = plan_optimal(h, RULES)
    st = patient_status(h, plan, RULES)
    assert st.powered[st.life_support].all()


def test_tiny_generator_still_returns_a_plan():
    h = make_hospital(generator={"rated_kw": 40})
    plan = plan_optimal(h, RULES)
    assert plan.kept is not None and plan.notes  # explains the shortfall


# ---------- fuel ----------

def test_fuel_formula_hand_calc():
    # 300 kW set at 250 kW: 0.08145*300 + 0.246*250 = 85.935 L/h
    assert math.isclose(fuel.burn_rate(250, 300), 85.935, rel_tol=1e-9)
    assert math.isclose(fuel.runtime_h(859.35, 250, 300), 10.0, rel_tol=1e-9)
    load = fuel.fuel_safe_load(859.35, 10.0, 300)
    assert math.isclose(load, 250, rel_tol=1e-9)


# ---------- pre-outage check ----------

def test_precheck_finds_injected_faults():
    h = make_hospital(faults=("lift_a_off_backup", "lift_b_off_backup", "isolation_off_backup"))
    found = set(precheck(h, RULES)["check"])
    assert {"Life support not on backup", "Lift not on backup",
            "No powered evacuation route"} <= found


def test_unknown_device_treated_as_life_support():
    h = make_hospital()
    h.patients.loc[0, "devices"] = "ecmo"
    p = patient_needs(h.patients, RULES)
    assert p.loc[0, "life_support"] and p.loc[0, "weight"] == 100
    assert "Data gap" in set(precheck(h, RULES)["check"])


# ---------- what-if and Excel ----------

def test_whatif_generator_failure_halves_capacity():
    h = make_hospital()
    w = apply_whatif(h, gen_fail_pct=50)
    assert w.generator["rated_kw"] == h.generator["rated_kw"] / 2
    assert h.generator["rated_kw"] == 300  # original untouched


def test_excel_round_trip():
    h = make_hospital()
    h2 = from_excel(__import__("io").BytesIO(to_excel_bytes(h)))
    assert len(h2.patients) == len(h.patients)
    assert plan_optimal(h2, RULES).kept == plan_optimal(h, RULES).kept
