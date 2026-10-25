"""Patient-to-Power Triage - dashboard.

    .venv/bin/streamlit run app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui
from data.generate import make_hospital
from engine.baseline import plan_baseline
from engine.danger_clock import danger_clock
from engine.model import from_excel, load_rules, to_excel_bytes
from engine.plan import circuit_loads, summarize
from engine.planner import plan_optimal
from engine.precheck import precheck
from engine.whatif import apply_whatif

SIM_DIR = Path(__file__).parent / "sim"
DISCLAIMER = ("Advisor only - staff make the final decision. Priority rules are examples "
              "that must be approved by the hospital's doctors. All data is simulated.")

st.set_page_config(page_title="Patient-to-Power Triage", page_icon="⚡", layout="wide")
rules = load_rules()

# ---------------- state ----------------
if "hospital" not in st.session_state:
    st.session_state.hospital = make_hospital()
    st.session_state.plans = None


def reset_plans():
    st.session_state.plans = None


def make_plans(h):
    return {"planner": plan_optimal(h, rules), "baseline": plan_baseline(h, rules)}


# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Hospital data")
    src = st.radio("Source", ["Fake government hospital", "Upload Excel"], label_visibility="collapsed")
    if src == "Fake government hospital":
        seed = st.number_input("Scenario seed", 1, 9999, 7, help="Different seed = different night")
        occ = st.slider("Bed occupancy", 0.6, 1.1, 0.9, 0.05)
        overflow = st.slider("ICU overflow (ventilated patients in wards)", 0.0, 0.5, 0.2, 0.05)
        if st.button("Load fake hospital"):
            st.session_state.hospital = make_hospital(seed=int(seed), occupancy=occ, overflow=overflow)
            reset_plans()
    else:
        up = st.file_uploader("Workbook (.xlsx)", type=["xlsx"])
        if up is not None and st.button("Use this workbook"):
            try:
                st.session_state.hospital = from_excel(up)
                reset_plans()
                st.success("Loaded.")
            except Exception as e:  # show the problem to the user instead of crashing
                st.error(f"Could not read workbook: {e}")
    st.download_button("Download data / Excel template", to_excel_bytes(st.session_state.hospital),
                       "hospital_template.xlsx")

    h = st.session_state.hospital
    g = h.generator
    st.header("Generator now")
    g["rated_kw"] = st.number_input("Generator rating (kW)", 10.0, 5000.0, float(g["rated_kw"]), 25.0)
    g["tank_l"] = st.number_input("Tank size (L)", 50.0, 20000.0, float(g["tank_l"]), 50.0)
    g["fuel_l"] = st.number_input("Diesel in tank (L)", 0.0, float(g["tank_l"]),
                                  min(float(g["fuel_l"]), float(g["tank_l"])), 25.0)
    g["expected_outage_h"] = st.number_input("Expected outage (h)", 0.5, 72.0,
                                             float(g["expected_outage_h"]), 0.5)
    g["refuel_eta_h"] = st.number_input("Diesel tanker arrives in (h)", 0.5, 72.0,
                                        float(g["refuel_eta_h"]), 0.5)
    if st.button("⚡ Generator ON - make plan", type="primary", width="stretch"):
        with st.spinner("Planning..."):
            st.session_state.plans = make_plans(h)

h = st.session_state.hospital
sig = (id(h), tuple(h.generator.values()))  # re-plan whenever the generator inputs change
if st.session_state.plans is None or st.session_state.get("plan_sig") != sig:
    st.session_state.plans = make_plans(h)
    st.session_state.plan_sig = sig
plans = st.session_state.plans
plan, base = plans["planner"], plans["baseline"]
s, sb = summarize(h, plan, rules), summarize(h, base, rules)

# ---------------- header ----------------
st.markdown(ui.CSS, unsafe_allow_html=True)
st.markdown('<div class="pt-hero"><h1>⚡ Patient-to-Power Triage</h1>'
            '<p>When the generator can\'t carry the whole hospital, every litre of diesel should '
            'reach the patient who can\'t wait.</p></div>', unsafe_allow_html=True)

tab_demo, tab_plan, tab_clock, tab_whatif, tab_check, tab_evidence, tab_data = st.tabs(
    ["🏥 Live demo", "Plan details", "Danger clock", "What-if", "Pre-outage check",
     "Evidence (50 outages)", "Hospital data"])


def fmt_h(x):
    return "∞" if x == float("inf") else f"{x:.1f} h"


# ---------------- Live demo ----------------
with tab_demo:
    c1, c2 = st.columns([2, 1])
    mode = c1.radio("Who decides what stays on?", ["Today: fixed department list",
                                                    "Our patient-aware plan"], horizontal=True)
    fail = c2.toggle("⚠️ Generator set 2 fails (−50%)")
    hd = apply_whatif(h, gen_fail_pct=50) if fail else h
    if fail:
        dplan, dbase = plan_optimal(hd, rules), plan_baseline(hd, rules)
    else:
        dplan, dbase = plan, base
    shown = dplan if mode.startswith("Our") else dbase
    ds, db = summarize(hd, dplan, rules), summarize(hd, dbase, rules)
    cur = ds if shown is dplan else db
    lost = cur["life_support_total"] - cur["life_support_powered"]
    st.markdown(ui.cards([
        ("Life-support patients powered", f"{cur['life_support_powered']} / {cur['life_support_total']}",
         "everyone on life support" if lost == 0 else f"{lost} patients left without power",
         "good" if lost == 0 else "bad"),
        ("Diesel lasts", fmt_h(cur["runtime_h"]),
         f"need {cur['hours_needed']:.0f} h until tanker / power back",
         "good" if cur["runtime_h"] >= cur["hours_needed"] else "warn"),
        ("Generator power wasted", f"{cur['nonessential_kw']:.0f} kW",
         "on empty theatres, offices, corridors", "good" if cur["nonessential_kw"] < 10 else "bad"),
        ("Diesel burn", f"{cur['burn_lph']:.0f} L/h",
         f"generator {cur['capacity_kw']:.0f} kW · load {cur['kept_kw']:.0f} kW", "info"),
    ]), unsafe_allow_html=True)
    left, right = st.columns([3, 1])
    with left:
        st.markdown(ui.hospital_map(hd, shown, rules), unsafe_allow_html=True)
    with right:
        st.markdown("**What staff are told to do**")
        if shown is dbase:
            st.markdown("Fixed list: keep departments in order until the generator is full. "
                        "No patient moves. Doesn't know who is on life support where.")
        else:
            for m in dplan.moves[:8]:
                route = f"via {m['lift']}" if m["cross_floor"] else "same floor"
                st.markdown(f'<div class="pt-move">🛏️ Move <b>{m["patient"]}</b> '
                            f'({m["devices"].replace(";", ", ")})<br>{m["from_room"]} → '
                            f'<b>{m["to_room"]}</b> · ✅ {route}</div>', unsafe_allow_html=True)
            if len(dplan.moves) > 8:
                st.caption(f"+ {len(dplan.moves) - 8} more moves in Plan details")
            for d in dplan.delayed_surgeries:
                st.markdown(f'<div class="pt-move">⏸️ Delay {d["procedure"]} ({d["room"]})</div>',
                            unsafe_allow_html=True)
            cut_names = [c for c in hd.circuits.set_index("id").loc[
                sorted(set(hd.circuits[hd.circuits.on_backup].id) - dplan.kept), "name"]]
            st.markdown(f"**Switch off:** {', '.join(cut_names)}")
    st.markdown(f'<div class="pt-foot">{DISCLAIMER}</div>', unsafe_allow_html=True)


# ---------------- Plan ----------------
with tab_plan:
    k = st.columns(5)
    k[0].metric("Normal demand", f"{s['demand_kw']:.0f} kW", f"generator {s['capacity_kw']:.0f} kW",
                delta_color="off")
    k[1].metric("Load kept on generator", f"{s['kept_kw']:.0f} kW", f"{s['load_pct']:.0f}% of rating",
                delta_color="off")
    k[2].metric("Diesel lasts", fmt_h(s["runtime_h"]),
                f"{s['runtime_h'] - sb['runtime_h']:+.1f} h vs fixed list")
    k[3].metric("Life-support patients powered", f"{s['life_support_powered']}/{s['life_support_total']}",
                f"{s['life_support_powered'] - sb['life_support_powered']:+d} vs fixed list")
    k[4].metric("Diesel burn", f"{s['burn_lph']:.0f} L/h",
                f"{s['burn_lph'] - sb['burn_lph']:+.1f} L/h vs fixed list", delta_color="inverse")

    if s["runtime_h"] < s["hours_needed"]:
        st.warning(f"Even with this plan the diesel lasts {fmt_h(s['runtime_h'])}, less than the "
                   f"{s['hours_needed']:.1f} h needed. Arrange fuel now.")
    for n in plan.notes:
        st.error(n)
    st.caption(f"Solver: {plan.status}, {plan.solve_s:.2f} s")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Circuits: keep or cut")
        loads = circuit_loads(h, plan, rules)
        loads["action"] = loads.apply(
            lambda r: "KEEP" if r["kept"] else ("NOT ON GENERATOR" if not r["on_backup"] else "CUT"),
            axis=1)
        view = loads[["action", "id", "name", "floor", "kind", "load_kw", "base_kw", "patients",
                      "life_support_patients"]].sort_values(["action", "floor", "id"],
                                                            ascending=[False, True, True])

        def colour(row):
            c = {"KEEP": "#d9f2e3", "CUT": "#fde2e1", "NOT ON GENERATOR": "#eeeeee"}[row["action"]]
            return [f"background-color: {c}; color: #111"] * len(row)

        st.dataframe(view.style.apply(colour, axis=1).format({"load_kw": "{:.1f}", "base_kw": "{:.1f}"}),
                     hide_index=True, height=560)
    with right:
        st.subheader("Patients to move")
        if plan.moves:
            mv = pd.DataFrame(plan.moves)
            mv["route check"] = mv.apply(
                lambda r: f"✅ via {r['lift']}" if r["cross_floor"] else "✅ same floor", axis=1)
            mv["support"] = mv["manual_support"].map(
                {True: "⚠️ bag / O₂ cylinder during move", False: "device battery OK"})
            st.dataframe(mv[["patient", "name", "devices", "from_room", "to_room", "route check",
                             "transport_min", "support"]], hide_index=True)
        else:
            st.write("No moves needed.")
        st.subheader("Surgeries to delay")
        if plan.delayed_surgeries:
            st.dataframe(pd.DataFrame(plan.delayed_surgeries), hide_index=True)
        else:
            st.write("None.")
        st.subheader("Compared with today's fixed list")
        comp = pd.DataFrame({
            "Fixed list (today)": [sb["life_support_powered"], sb["patients_powered"], sb["kept_kw"],
                                   sb["burn_lph"], sb["runtime_h"], 0],
            "Patient-aware plan": [s["life_support_powered"], s["patients_powered"], s["kept_kw"],
                                   s["burn_lph"], s["runtime_h"], s["moves"]],
        }, index=["Life-support patients powered", "All patients powered", "Load (kW)",
                  "Diesel burn (L/h)", "Runtime (h)", "Planned moves"]).round(1)
        st.dataframe(comp)

    text = [f"POWER PLAN - generator {s['capacity_kw']:.0f} kW, diesel {g['fuel_l']:.0f} L",
            f"Keep {s['kept_kw']:.0f} kW; diesel lasts {fmt_h(s['runtime_h'])}.", "", "CUT these circuits:"]
    text += [f"  - {r['id']} {r['name']}" for _, r in loads[~loads.kept & loads.on_backup].iterrows()]
    text += ["", "MOVE these patients:"]
    text += [f"  - {m['patient']} ({m['devices']}): {m['from_room']} -> {m['to_room']}" for m in plan.moves]
    text += ["", "DELAY these surgeries:"] + [f"  - {d['surgery']} {d['procedure']}" for d in plan.delayed_surgeries]
    text += ["", DISCLAIMER]
    st.download_button("Download printable plan", "\n".join(text), "power_plan.txt")

# ---------------- Danger clock ----------------
with tab_clock:
    which = st.radio("Plan", ["Patient-aware plan", "Fixed list (today)"], horizontal=True)
    dc = danger_clock(h, plan if which.startswith("Patient") else base, rules)
    c1, c2, c3 = st.columns(3)
    c1.metric("🔴 Under 30 min", int((dc.level == "RED").sum()))
    c2.metric("🟠 Under 2 h", int((dc.level == "AMBER").sum()))
    c3.metric("🟢 Safe longer", int((dc.level == "GREEN").sum()))
    dc_show = dc.copy()
    dc_show["minutes_left"] = dc_show["minutes_left"].map(lambda x: "until refuel" if x == float("inf")
                                                          else f"{x:.0f}")

    def lvl(row):
        c = {"RED": "#fde2e1", "AMBER": "#fff1d6", "GREEN": "#d9f2e3"}[row["level"]]
        return [f"background-color: {c}; color: #111"] * len(row)

    st.dataframe(dc_show.style.apply(lvl, axis=1), hide_index=True, height=600)

# ---------------- What-if ----------------
with tab_whatif:
    st.write("Test the plan against things going wrong.")
    a, b = st.columns(2)
    gen_fail = a.slider("Generator capacity lost (%)", 0, 75, 50, 5,
                        help="50% = one of two generator sets fails")
    fuel_drop = a.slider("Fuel lost (%)", 0, 75, 0, 5)
    extra = b.slider("Outage lasts longer by (h)", 0, 24, 0)
    delay = b.slider("Tanker late by (h)", 0, 24, 0)
    w = apply_whatif(h, gen_fail, fuel_drop, extra, delay)
    wp, wb = plan_optimal(w, rules), plan_baseline(w, rules)
    rows = {"Now - patient-aware": s, "What-if - patient-aware": summarize(w, wp, rules),
            "What-if - fixed list": summarize(w, wb, rules)}
    tbl = pd.DataFrame({k: {"Generator (kW)": f"{v['capacity_kw']:.0f}",
                            "Load kept (kW)": f"{v['kept_kw']:.1f}",
                            "Diesel lasts (h)": fmt_h(v["runtime_h"]),
                            "Life-support powered": f"{v['life_support_powered']}/{v['life_support_total']}",
                            "Moves": v["moves"], "Surgeries delayed": v["delayed_surgeries"]}
                        for k, v in rows.items()})
    st.dataframe(tbl.astype(str))
    if wp.moves:
        st.write("Extra moves needed in this what-if:")
        st.dataframe(pd.DataFrame(wp.moves)[["patient", "devices", "from_room", "to_room", "lift"]],
                     hide_index=True)

# ---------------- Pre-outage check ----------------
with tab_check:
    st.write("Run this on a normal day to find problems before the power fails.")
    pc = precheck(h, rules)
    if pc.empty:
        st.success("No problems found.")
    else:
        n_high = int((pc.severity == "High").sum())
        st.metric("High-severity problems", n_high)

        def sev(row):
            c = {"High": "#fde2e1", "Medium": "#fff1d6", "Low": "#e8eefc"}[row["severity"]]
            return [f"background-color: {c}; color: #111"] * len(row)

        st.dataframe(pc.style.apply(sev, axis=1), hide_index=True)

# ---------------- Evidence ----------------
with tab_evidence:
    res_path = SIM_DIR / "results.csv"
    if st.button("Re-run 50-outage simulation (~10 s)"):
        from sim.run_sim import run_all
        with st.spinner("Simulating 50 outages..."):
            run_all(log=False).to_csv(res_path, index=False)
    if not res_path.exists():
        st.info("No simulation results yet - press the button above.")
    else:
        d = pd.read_csv(res_path)
        bl = d[d.method.str.startswith("Fixed")].set_index("scenario")
        pl = d[d.method.str.startswith("Patient")].set_index("scenario")

        def pct(a, b):
            return 100 * (a - b) / a if a else 0.0

        m = st.columns(4)
        m[0].metric("Life-support patient-minutes without power",
                    f"{pl.ls_patient_minutes_without_power.sum():,.0f}",
                    f"-{pct(bl.ls_patient_minutes_without_power.sum(), pl.ls_patient_minutes_without_power.sum()):.0f}% vs fixed list",
                    delta_color="inverse")
        m[1].metric("Full-blackout minutes (fuel ran out)", f"{pl.blackout_min.sum():,.0f}",
                    f"-{pct(bl.blackout_min.sum(), pl.blackout_min.sum()):.0f}%", delta_color="inverse")
        m[2].metric("Average diesel burn", f"{pl.burn_lph.mean():.1f} L/h",
                    f"-{pct(bl.burn_lph.mean(), pl.burn_lph.mean()):.0f}%", delta_color="inverse")
        m[3].metric("Runtime per full tank", f"{pl.runtime_per_tank_h.mean():.1f} h",
                    f"+{pl.runtime_per_tank_h.mean() - bl.runtime_per_tank_h.mean():.1f} h")
        m2 = st.columns(4)
        m2[0].metric("Life-support patients cut off at start", int(pl.ls_unpowered_at_start.sum()),
                     f"{int(pl.ls_unpowered_at_start.sum() - bl.ls_unpowered_at_start.sum())} vs fixed list",
                     delta_color="inverse")
        m2[1].metric("Stranded upstairs with no lift", int(pl.stranded_no_lift.sum()),
                     f"{int(pl.stranded_no_lift.sum() - bl.stranded_no_lift.sum())}", delta_color="inverse")
        m2[2].metric("Planner never worse than fixed list",
                     f"{int((pl.ls_patient_minutes_without_power <= bl.ls_patient_minutes_without_power + 1e-6).sum())}/{len(pl)}")
        diesel_per_h = bl.burn_lph.mean() - pl.burn_lph.mean()
        m2[3].metric("Diesel saved per outage hour", f"{diesel_per_h:.1f} L",
                     f"≈ ₹{diesel_per_h * 90:,.0f} · {diesel_per_h * 2.68:.0f} kg CO₂", delta_color="off")

        if "nonessential_share" in d:
            st.markdown(ui.cards([
                ("Generator power wasted on empty loads · today",
                 f"{100 * bl.nonessential_share.mean():.0f}%",
                 f"{bl.nonessential_kw.mean():.0f} kW on empty theatres, offices, corridors", "bad"),
                ("Generator power wasted on empty loads · our plan",
                 f"{100 * pl.nonessential_share.mean():.0f}%",
                 f"{pl.nonessential_kw.mean():.0f} kW", "good"),
            ]), unsafe_allow_html=True)

        fig = go.Figure()
        fig.add_bar(x=bl.index, y=bl.ls_patient_minutes_without_power, name="Fixed list (today)",
                    marker_color="#d1495b")
        fig.add_bar(x=pl.index, y=pl.ls_patient_minutes_without_power, name="Patient-aware planner",
                    marker_color="#2e8b57")
        fig.update_layout(title="Life-support patient-minutes without power, per simulated outage",
                          xaxis_title="Scenario", yaxis_title="Patient-minutes", barmode="group",
                          height=420, legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, width="stretch")

        c1, c2 = st.columns(2)
        c1.plotly_chart(px.box(d, x="method", y="burn_lph", color="method", points="all",
                               title="Diesel burn rate (L/h)",
                               color_discrete_sequence=["#d1495b", "#2e8b57"]).update_layout(showlegend=False),
                        width="stretch")
        c2.plotly_chart(px.box(d, x="method", y="blackout_min", color="method", points="all",
                               title="Minutes of full blackout (fuel ran out)",
                               color_discrete_sequence=["#d1495b", "#2e8b57"]).update_layout(showlegend=False),
                        width="stretch")

        sens = SIM_DIR / "sensitivity.csv"
        if sens.exists():
            st.subheader("Sensitivity: does the result hold if our assumptions are off by 20%?")
            sd = pd.read_csv(sens).groupby(["variant", "method"])[
                ["ls_patient_minutes_without_power", "blackout_min", "burn_lph"]].mean().round(1)
            st.dataframe(sd)
        with st.expander("All scenario results"):
            st.dataframe(d, hide_index=True)

# ---------------- Data ----------------
with tab_data:
    st.write("Edit the tables, then press **Apply edits**. Paper records can be typed in here.")
    edited = {}
    for name in ["patients", "circuits", "rooms", "surgeries"]:
        st.subheader(name.capitalize())
        edited[name] = st.data_editor(getattr(h, name), num_rows="dynamic", key=f"ed_{name}",
                                      hide_index=True)
    if st.button("Apply edits"):
        for name, df in edited.items():
            setattr(h, name, df)
        st.session_state.plans = make_plans(h)
        st.success("Plan updated with your edits.")

st.caption(DISCLAIMER)
