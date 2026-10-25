"""Build a static copy of the dashboard for hosting on Vercel.

Vercel cannot run Streamlit, so this precomputes everything the dashboard
shows for the default fake hospital - all 7 tabs, both demo states, and every
What-if slider combination - and writes site/static.html (+ the Excel file).

    .venv/bin/python export_static.py
"""
from __future__ import annotations

import itertools
import json

from html import escape
from pathlib import Path

import pandas as pd

import ui
from data.generate import make_hospital
from engine.baseline import plan_baseline
from engine.danger_clock import danger_clock
from engine.model import load_rules, to_excel_bytes
from engine.plan import circuit_loads, summarize
from engine.planner import plan_optimal
from engine.precheck import precheck
from engine.whatif import apply_whatif

ROOT = Path(__file__).parent
OUT = ROOT / "site"
DISCLAIMER = ("Advisor only - staff make the final decision. Priority rules are examples that "
              "must be approved by the hospital's doctors. All data is simulated.")
ROW_BG = {"KEEP": "#d9f2e3", "CUT": "#fde2e1", "NOT ON GENERATOR": "#eeeeee", "RED": "#fde2e1",
          "AMBER": "#fff1d6", "GREEN": "#d9f2e3", "High": "#fde2e1", "Medium": "#fff1d6", "Low": "#e8eefc"}

# What-if slider steps (each combination is planned in advance)
GEN_FAIL = [0, 25, 50, 75]
FUEL_LOST = [0, 25, 50]
EXTRA_H = [0, 6, 12]
LATE_H = [0, 6, 12]


def fmt_h(x):
    return "∞" if x == float("inf") else f"{x:.1f} h"


def table(df: pd.DataFrame, colour_col: str | None = None, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    head = "".join(f"<th>{escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        style = f' style="background:{ROW_BG.get(str(r[colour_col]), "#fff")}"' if colour_col else ""
        cells = "".join(f"<td>{escape(fmt[c](v) if c in fmt else ('' if pd.isna(v) else str(v)))}</td>"
                        for c, v in r.items())
        rows.append(f"<tr{style}>{cells}</tr>")
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def metric(label, value, delta="", tone=""):
    return (f'<div class="mt"><div class="ml">{escape(label)}</div><div class="mv">{escape(value)}</div>'
            f'<div class="md {tone}">{escape(delta)}</div></div>')


# ---------------- tab builders ----------------

def demo_panel(h, plan, is_ours, rules) -> str:
    s = summarize(h, plan, rules)
    lost = s["life_support_total"] - s["life_support_powered"]
    cards = ui.cards([
        ("Life-support patients powered", f"{s['life_support_powered']} / {s['life_support_total']}",
         "everyone on life support" if lost == 0 else f"{lost} patients left without power",
         "good" if lost == 0 else "bad"),
        ("Diesel lasts", fmt_h(s["runtime_h"]), f"need {s['hours_needed']:.0f} h until tanker / power back",
         "good" if s["runtime_h"] >= s["hours_needed"] else "warn"),
        ("Generator power wasted", f"{s['nonessential_kw']:.0f} kW", "on empty theatres, offices, corridors",
         "good" if s["nonessential_kw"] < 10 else "bad"),
        ("Diesel burn", f"{s['burn_lph']:.0f} L/h",
         f"generator {s['capacity_kw']:.0f} kW · load {s['kept_kw']:.0f} kW", "info"),
    ])
    if not is_ours:
        todo = ("<p>Fixed list: keep departments in order until the generator is full. No patient moves. "
                "Doesn't know who is on life support where.</p>")
    else:
        items = []
        for m in plan.moves[:8]:
            route = f"via {m['lift']}" if m["cross_floor"] else "same floor"
            items.append(f'<div class="pt-move">🛏️ Move <b>{escape(m["patient"])}</b> '
                         f'({escape(m["devices"].replace(";", ", "))})<br>{escape(m["from_room"])} → '
                         f'<b>{escape(m["to_room"])}</b> · ✅ {escape(route)}</div>')
        if len(plan.moves) > 8:
            items.append(f'<p class="note">+ {len(plan.moves) - 8} more moves in Plan details</p>')
        for d in plan.delayed_surgeries:
            items.append(f'<div class="pt-move">⏸️ Delay {escape(d["procedure"])} ({escape(d["room"])})</div>')
        c = h.circuits.set_index("id")
        cut = sorted(set(h.circuits[h.circuits.on_backup].id) - plan.kept)
        items.append(f"<p><b>Switch off:</b> {escape(', '.join(c.loc[cut, 'name']))}</p>")
        todo = "".join(items)
    return (f"{cards}<div class='pt-grid'><div>{ui.hospital_map(h, plan, rules)}</div>"
            f"<aside><p><b>What staff are told to do</b></p>{todo}</aside></div>")


def tab_demo(h, rules) -> str:
    hf = apply_whatif(h, gen_fail_pct=50)
    panels = []
    for key, hh in (("ok", h), ("fail", hf)):
        panels.append(f'<section class="dpanel" id="d-base-{key}">{demo_panel(hh, plan_baseline(hh, rules), False, rules)}</section>')
        panels.append(f'<section class="dpanel" id="d-ours-{key}">{demo_panel(hh, plan_optimal(hh, rules), True, rules)}</section>')
    return f"""
<div class="row2">
  <div><div class="lbl2">Who decides what stays on?</div>
    <label class="radio"><input type="radio" name="who" value="base" checked> Today: fixed department list</label>
    <label class="radio"><input type="radio" name="who" value="ours"> Our patient-aware plan</label></div>
  <label class="switch"><input type="checkbox" id="fail"><span class="sl"></span> ⚠️ Generator set 2 fails (−50%)</label>
</div>
{''.join(panels)}
<div class="pt-foot">{escape(DISCLAIMER)}</div>"""


def tab_plan(h, plan, base, rules) -> str:
    s, sb = summarize(h, plan, rules), summarize(h, base, rules)
    m = "".join([
        metric("Normal demand", f"{s['demand_kw']:.0f} kW", f"generator {s['capacity_kw']:.0f} kW"),
        metric("Load kept on generator", f"{s['kept_kw']:.0f} kW", f"{s['load_pct']:.0f}% of rating"),
        metric("Diesel lasts", fmt_h(s["runtime_h"]), f"{s['runtime_h'] - sb['runtime_h']:+.1f} h vs fixed list", "up"),
        metric("Life-support patients powered", f"{s['life_support_powered']}/{s['life_support_total']}",
               f"{s['life_support_powered'] - sb['life_support_powered']:+d} vs fixed list", "up"),
        metric("Diesel burn", f"{s['burn_lph']:.0f} L/h", f"{s['burn_lph'] - sb['burn_lph']:+.1f} L/h vs fixed list", "up"),
    ])
    loads = circuit_loads(h, plan, rules)
    loads["action"] = loads.apply(lambda r: "KEEP" if r["kept"] else ("NOT ON GENERATOR" if not r["on_backup"] else "CUT"), axis=1)
    view = loads[["action", "id", "name", "floor", "kind", "load_kw", "base_kw", "patients", "life_support_patients"]] \
        .sort_values(["action", "floor", "id"], ascending=[False, True, True])
    circ = table(view, "action", {"load_kw": lambda v: f"{v:.1f}", "base_kw": lambda v: f"{v:.1f}"})
    if plan.moves:
        mv = pd.DataFrame(plan.moves)
        mv["route check"] = mv.apply(lambda r: f"✅ via {r['lift']}" if r["cross_floor"] else "✅ same floor", axis=1)
        mv["support"] = mv["manual_support"].map({True: "⚠️ bag / O₂ cylinder during move", False: "device battery OK"})
        moves = table(mv[["patient", "name", "devices", "from_room", "to_room", "route check", "transport_min", "support"]])
    else:
        moves = "<p>No moves needed.</p>"
    delayed = table(pd.DataFrame(plan.delayed_surgeries)) if plan.delayed_surgeries else "<p>None.</p>"
    comp = pd.DataFrame({
        "": ["Life-support patients powered", "All patients powered", "Load (kW)", "Diesel burn (L/h)", "Runtime (h)", "Planned moves"],
        "Fixed list (today)": [sb["life_support_powered"], sb["patients_powered"], round(sb["kept_kw"], 1),
                               round(sb["burn_lph"], 1), round(sb["runtime_h"], 1), 0],
        "Patient-aware plan": [s["life_support_powered"], s["patients_powered"], round(s["kept_kw"], 1),
                               round(s["burn_lph"], 1), round(s["runtime_h"], 1), s["moves"]]})
    return f"""<div class="metrics">{m}</div><p class="note">Solver: {escape(plan.status)}, {plan.solve_s:.2f} s</p>
<div class="cols"><div><h3>Circuits: keep or cut</h3>{circ}</div>
<div><h3>Patients to move</h3>{moves}<h3>Surgeries to delay</h3>{delayed}
<h3>Compared with today's fixed list</h3>{table(comp)}
<p><a class="btn" href="power_plan.txt" download>Download printable plan</a></p></div></div>"""


def plan_text(h, plan, rules) -> str:
    s = summarize(h, plan, rules)
    loads = circuit_loads(h, plan, rules)
    t = [f"POWER PLAN - generator {s['capacity_kw']:.0f} kW, diesel {h.generator['fuel_l']:.0f} L",
         f"Keep {s['kept_kw']:.0f} kW; diesel lasts {fmt_h(s['runtime_h'])}.", "", "CUT these circuits:"]
    t += [f"  - {r['id']} {r['name']}" for _, r in loads[~loads.kept & loads.on_backup].iterrows()]
    t += ["", "MOVE these patients:"] + [f"  - {m['patient']} ({m['devices']}): {m['from_room']} -> {m['to_room']}" for m in plan.moves]
    t += ["", "DELAY these surgeries:"] + [f"  - {d['surgery']} {d['procedure']}" for d in plan.delayed_surgeries]
    return "\n".join(t + ["", DISCLAIMER])


def clock_block(h, plan, rules) -> str:
    dc = danger_clock(h, plan, rules)
    counts = "".join([metric("🔴 Under 30 min", str(int((dc.level == "RED").sum()))),
                      metric("🟠 Under 2 h", str(int((dc.level == "AMBER").sum()))),
                      metric("🟢 Safe longer", str(int((dc.level == "GREEN").sum())))])
    dc = dc.copy()
    dc["minutes_left"] = dc["minutes_left"].map(lambda x: "until refuel" if x == float("inf") else f"{x:.0f}")
    return f'<div class="metrics">{counts}</div>{table(dc, "level")}'


def tab_clock(h, plan, base, rules) -> str:
    return f"""<div class="lbl2">Plan</div>
<label class="radio"><input type="radio" name="clk" value="ours" checked> Patient-aware plan</label>
<label class="radio"><input type="radio" name="clk" value="base"> Fixed list (today)</label>
<section class="cpanel" id="c-ours">{clock_block(h, plan, rules)}</section>
<section class="cpanel" id="c-base">{clock_block(h, base, rules)}</section>"""


def tab_whatif(h, rules) -> tuple[str, dict]:
    s_now = summarize(h, plan_optimal(h, rules), rules)
    results = {}
    for g, f, e, d in itertools.product(GEN_FAIL, FUEL_LOST, EXTRA_H, LATE_H):
        w = apply_whatif(h, g, f, e, d)
        wp, wb = plan_optimal(w, rules), plan_baseline(w, rules)
        rows = {"Now - patient-aware": s_now, "What-if - patient-aware": summarize(w, wp, rules),
                "What-if - fixed list": summarize(w, wb, rules)}
        tbl = pd.DataFrame({"": ["Generator (kW)", "Load kept (kW)", "Diesel lasts (h)", "Life-support powered",
                                 "Moves", "Surgeries delayed"],
                            **{k: [f"{v['capacity_kw']:.0f}", f"{v['kept_kw']:.1f}", fmt_h(v["runtime_h"]),
                                   f"{v['life_support_powered']}/{v['life_support_total']}", str(v["moves"]),
                                   str(v["delayed_surgeries"])] for k, v in rows.items()}})
        html = table(tbl)
        if wp.moves:
            html += "<p>Extra moves needed in this what-if:</p>" + table(
                pd.DataFrame(wp.moves)[["patient", "devices", "from_room", "to_room", "lift"]])
        results[f"{g}-{f}-{e}-{d}"] = html

    def sel(id_, label, opts, unit, default):
        o = "".join(f'<option value="{v}"{" selected" if v == default else ""}>{v}{unit}</option>' for v in opts)
        return f'<label class="sel"><span>{escape(label)}</span><select id="{id_}">{o}</select></label>'

    ui_html = f"""<p>Test the plan against things going wrong.</p>
<div class="sels">{sel("w-g", "Generator capacity lost", GEN_FAIL, "%", 50)}{sel("w-f", "Fuel lost", FUEL_LOST, "%", 0)}
{sel("w-e", "Outage lasts longer by", EXTRA_H, " h", 0)}{sel("w-d", "Tanker late by", LATE_H, " h", 0)}</div>
<div id="w-out"></div>"""
    return ui_html, results


def tab_check(h, rules) -> str:
    pc = precheck(h, rules)
    if pc.empty:
        return "<p>No problems found.</p>"
    return (f'<p>Run this on a normal day to find problems before the power fails.</p>'
            f'<div class="metrics">{metric("High-severity problems", str(int((pc.severity == "High").sum())))}</div>'
            f'{table(pc, "severity")}')


def tab_evidence() -> tuple[str, dict]:
    d = pd.read_csv(ROOT / "sim" / "results.csv")
    b = d[d.method.str.startswith("Fixed")].set_index("scenario")
    p = d[d.method.str.startswith("Patient")].set_index("scenario")
    x = "ls_patient_minutes_without_power"
    pct = lambda a, c: 100 * (a - c) / a if a else 0
    saved = b.burn_lph.mean() - p.burn_lph.mean()
    m1 = "".join([
        metric("Life-support patient-minutes without power", f"{p[x].sum():,.0f}", f"-{pct(b[x].sum(), p[x].sum()):.0f}% vs fixed list", "down"),
        metric("Full-blackout minutes (fuel ran out)", f"{p.blackout_min.sum():,.0f}", f"-{pct(b.blackout_min.sum(), p.blackout_min.sum()):.0f}%", "down"),
        metric("Average diesel burn", f"{p.burn_lph.mean():.1f} L/h", f"-{pct(b.burn_lph.mean(), p.burn_lph.mean()):.0f}%", "down"),
        metric("Runtime per full tank", f"{p.runtime_per_tank_h.mean():.1f} h", f"+{p.runtime_per_tank_h.mean() - b.runtime_per_tank_h.mean():.1f} h", "down")])
    m2 = "".join([
        metric("Life-support patients cut off at start", str(int(p.ls_unpowered_at_start.sum())),
               f"{int(p.ls_unpowered_at_start.sum() - b.ls_unpowered_at_start.sum())} vs fixed list", "down"),
        metric("Stranded upstairs with no lift", str(int(p.stranded_no_lift.sum())),
               f"{int(p.stranded_no_lift.sum() - b.stranded_no_lift.sum())}", "down"),
        metric("Planner never worse than fixed list", f"{int((p[x] <= b[x] + 1e-6).sum())}/{len(p)}"),
        metric("Diesel saved per outage hour", f"{saved:.1f} L", f"≈ ₹{saved * 90:,.0f} · {saved * 2.68:.0f} kg CO₂")])
    waste = ui.cards([
        ("Generator power wasted on empty loads · today", f"{100 * b.nonessential_share.mean():.0f}%",
         f"{b.nonessential_kw.mean():.0f} kW on empty theatres, offices, corridors", "bad"),
        ("Generator power wasted on empty loads · our plan", f"{100 * p.nonessential_share.mean():.0f}%",
         f"{p.nonessential_kw.mean():.0f} kW", "good")])
    sens = ""
    if (ROOT / "sim" / "sensitivity.csv").exists():
        sd = pd.read_csv(ROOT / "sim" / "sensitivity.csv").groupby(["variant", "method"])[
            [x, "blackout_min", "burn_lph"]].mean().round(1).reset_index()
        sens = "<h3>Sensitivity: does the result hold if our assumptions are off by 20%?</h3>" + table(sd)
    allres = table(d.round(2))
    data = {"x": [int(i) for i in b.index], "base": b[x].round(0).tolist(), "ours": p[x].round(0).tolist(),
            "burn_b": b.burn_lph.round(1).tolist(), "burn_o": p.burn_lph.round(1).tolist(),
            "bo_b": b.blackout_min.round(0).tolist(), "bo_o": p.blackout_min.round(0).tolist()}
    html = f"""<div class="metrics">{m1}</div><div class="metrics">{m2}</div>{waste}
<div id="ch1" class="chart"></div><div class="cols2"><div id="ch2" class="chart"></div><div id="ch3" class="chart"></div></div>
{sens}<details><summary>All scenario results</summary>{allres}</details>"""
    return html, data


def tab_data(h) -> str:
    out = ['<p>On the live app these tables can be edited or uploaded. Here they are read-only. '
           '<a class="btn" href="hospital_template.xlsx" download>Download data / Excel template</a></p>']
    for name in ["patients", "circuits", "rooms", "surgeries"]:
        out.append(f"<h3>{name.capitalize()}</h3>{table(getattr(h, name))}")
    return "".join(out)


def sidebar(h) -> str:
    g = h.generator
    rows = [("Generator rating (kW)", f"{g['rated_kw']:.0f}"), ("Tank size (L)", f"{g['tank_l']:.0f}"),
            ("Diesel in tank (L)", f"{g['fuel_l']:.0f}"), ("Expected outage (h)", f"{g['expected_outage_h']:.1f}"),
            ("Diesel tanker arrives in (h)", f"{g['refuel_eta_h']:.1f}")]
    fields = "".join(f'<div class="fld"><span>{escape(a)}</span><div class="ro">{escape(b)}</div></div>' for a, b in rows)
    return f"""<aside class="side"><h2>Hospital data</h2>
<p>Fake government hospital<br><span class="note">seed 7 · occupancy 0.90 · ICU overflow 0.20</span></p>
<a class="btn" href="hospital_template.xlsx" download>Download data / Excel template</a>
<h2>Generator now</h2>{fields}</aside>"""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patient-to-Power Triage</title>
<meta name="description" content="Patient-aware backup power planning for hospitals - ENERGY SIMTECH'26 Track 3.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>">
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
__CSS__
<style>
:root {color-scheme: light;}
* {box-sizing: border-box;}
body {margin:0; background:#f7f9fb; color:#111827; font-family:"Source Sans Pro","Source Sans 3",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; font-size:16px;}
.layout {display:flex; min-height:100vh;}
.side {width:300px; flex:0 0 300px; background:#eef2f5; padding:24px 20px; border-right:1px solid #e3e8ef;}
.side h2 {font-size:1.25rem; margin:18px 0 10px;}
.fld {margin:10px 0;} .fld span {font-size:.85rem; color:#334155;} .ro {background:#fff; border-radius:8px; padding:8px 10px; margin-top:4px; border:1px solid #dbe2ea;}
.main {flex:1; min-width:0; padding:24px 32px 40px; max-width:1400px;}
.tabs {display:flex; gap:22px; border-bottom:1px solid #e3e8ef; margin:4px 0 16px; overflow-x:auto;}
.tabs button {background:none; border:0; padding:10px 0; font-size:.95rem; cursor:pointer; color:#334155; border-bottom:2px solid transparent; white-space:nowrap;}
.tabs button.on {color:#0f766e; border-bottom-color:#0f766e;}
.tab {display:none;} .tab.on {display:block;}
.dpanel, .cpanel {display:none;} .dpanel.on, .cpanel.on {display:block;}
.row2 {display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:6px;}
.lbl2 {font-size:.9rem; margin-bottom:4px;}
.radio {margin-right:18px; font-size:.95rem; cursor:pointer;} .radio input {accent-color:#0f766e;}
.switch {display:inline-flex; align-items:center; gap:8px; cursor:pointer; font-size:.95rem;}
.switch input {display:none;} .sl {width:36px; height:20px; border-radius:10px; background:#cbd5e1; position:relative; transition:.2s;}
.sl:after {content:""; position:absolute; left:2px; top:2px; width:16px; height:16px; border-radius:50%; background:#fff; transition:.2s;}
.switch input:checked + .sl {background:#0f766e;} .switch input:checked + .sl:after {left:18px;}
.pt-grid {display:grid; grid-template-columns:minmax(0,3fr) minmax(0,1fr); gap:18px;}
.cols {display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:24px;}
.cols2 {display:grid; grid-template-columns:1fr 1fr; gap:16px;}
.metrics {display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin:8px 0 12px;}
.mt .ml {font-size:.85rem; color:#334155;} .mt .mv {font-size:2rem; font-weight:600; line-height:1.3;}
.md {font-size:.85rem; color:#64748b; display:inline-block; padding:1px 8px; border-radius:10px; background:#eef2f5;}
.md.up, .md.down {color:#15803d; background:#dcfce7;}
.tbl {overflow:auto; max-height:560px; border:1px solid #e3e8ef; border-radius:8px; background:#fff; margin:6px 0 14px;}
table {border-collapse:collapse; width:100%; font-size:.85rem;}
th {position:sticky; top:0; background:#f1f5f9; text-align:left; padding:6px 8px; border-bottom:1px solid #e3e8ef; white-space:nowrap;}
td {padding:5px 8px; border-bottom:1px solid #eef2f5; color:#111;}
h3 {font-size:1.25rem; margin:14px 0 6px;}
.btn {display:inline-block; padding:8px 14px; border:1px solid #cbd5e1; border-radius:8px; background:#fff; color:#111827; text-decoration:none; font-size:.9rem;}
.sels {display:grid; grid-template-columns:1fr 1fr; gap:12px 28px; margin:10px 0 16px;}
.sel span {display:block; font-size:.9rem; margin-bottom:4px;} .sel select {width:100%; padding:8px; border-radius:8px; border:1px solid #cbd5e1; font-size:.95rem;}
.chart {width:100%; height:420px; background:#fff; border-radius:8px; margin:8px 0;}
details {margin:12px 0;} summary {cursor:pointer; font-weight:600;}
.note {font-size:.85rem; color:#64748b;}
code {background:#fff; padding:1px 4px; border-radius:4px;}
@media (max-width:900px) {
  .layout {flex-direction:column;} .side {width:auto; flex:none; border-right:0; border-bottom:1px solid #e3e8ef;}
  .main {padding:16px;} .pt-grid, .cols, .cols2, .sels {grid-template-columns:1fr;}
}
</style></head>
<body><div class="layout">
__SIDEBAR__
<div class="main">
<div class="pt-hero"><h1>⚡ Patient-to-Power Triage</h1>
<p>When the generator can't carry the whole hospital, every litre of diesel should reach the patient who can't wait.</p></div>
<nav class="tabs">
<button data-t="demo" class="on">🏥 Live demo</button><button data-t="plan">Plan details</button>
<button data-t="clock">Danger clock</button><button data-t="whatif">What-if</button>
<button data-t="check">Pre-outage check</button><button data-t="evidence">Evidence (50 outages)</button>
<button data-t="data">Hospital data</button></nav>
<div class="tab on" id="t-demo">__DEMO__</div>
<div class="tab" id="t-plan">__PLAN__</div>
<div class="tab" id="t-clock">__CLOCK__</div>
<div class="tab" id="t-whatif">__WHATIF__</div>
<div class="tab" id="t-check">__CHECK__</div>
<div class="tab" id="t-evidence">__EVIDENCE__</div>
<div class="tab" id="t-data">__DATA__</div>
<p class="note">__DISCLAIMER__</p>
</div></div>
<script>
const W = __WHATIF_DATA__, E = __EV_DATA__;
const $ = s => document.querySelector(s), $$ = s => document.querySelectorAll(s);
let charted = false;
function tab(t) {
  $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
  $$('.tab').forEach(x => x.classList.toggle('on', x.id === 't-' + t));
  if (t === 'evidence' && !charted) { charted = true; charts(); }
}
$$('.tabs button').forEach(b => b.onclick = () => tab(b.dataset.t));
function demo() {
  const who = $('input[name=who]:checked').value, f = $('#fail').checked ? 'fail' : 'ok';
  $$('.dpanel').forEach(p => p.classList.toggle('on', p.id === `d-${who}-${f}`));
}
$$('input[name=who]').forEach(i => i.onchange = demo); $('#fail').onchange = demo; demo();
function clk() { const v = $('input[name=clk]:checked').value; $$('.cpanel').forEach(p => p.classList.toggle('on', p.id === 'c-' + v)); }
$$('input[name=clk]').forEach(i => i.onchange = clk); clk();
function wi() { $('#w-out').innerHTML = W[[$('#w-g').value, $('#w-f').value, $('#w-e').value, $('#w-d').value].join('-')]; }
['#w-g', '#w-f', '#w-e', '#w-d'].forEach(s => $(s).onchange = wi); wi();
function charts() {
  if (!window.Plotly) return;
  const cfg = {responsive: true, displayModeBar: false}, R = '#d1495b', G = '#2e8b57';
  Plotly.newPlot('ch1', [
    {x: E.x, y: E.base, name: 'Fixed list (today)', type: 'bar', marker: {color: R}},
    {x: E.x, y: E.ours, name: 'Patient-aware planner', type: 'bar', marker: {color: G}}],
    {title: 'Life-support patient-minutes without power, per simulated outage', barmode: 'group',
     xaxis: {title: 'Scenario'}, yaxis: {title: 'Patient-minutes'}, legend: {orientation: 'h', y: 1.1}}, cfg);
  const box = (id, a, b, t) => Plotly.newPlot(id, [
    {y: a, name: 'Fixed list (today)', type: 'box', boxpoints: 'all', marker: {color: R}},
    {y: b, name: 'Patient-aware planner', type: 'box', boxpoints: 'all', marker: {color: G}}],
    {title: t, showlegend: false}, cfg);
  box('ch2', E.burn_b, E.burn_o, 'Diesel burn rate (L/h)');
  box('ch3', E.bo_b, E.bo_o, 'Minutes of full blackout (fuel ran out)');
}
</script>
</body></html>
"""


def main():
    rules = load_rules()
    h = make_hospital()
    plan, base = plan_optimal(h, rules), plan_baseline(h, rules)
    whatif_ui, whatif_data = tab_whatif(h, rules)
    ev_html, ev_data = tab_evidence()
    html = (PAGE.replace("__CSS__", ui.CSS).replace("__SIDEBAR__", sidebar(h))
            .replace("__DEMO__", tab_demo(h, rules)).replace("__PLAN__", tab_plan(h, plan, base, rules))
            .replace("__CLOCK__", tab_clock(h, plan, base, rules)).replace("__WHATIF__", whatif_ui)
            .replace("__CHECK__", tab_check(h, rules)).replace("__EVIDENCE__", ev_html)
            .replace("__DATA__", tab_data(h)).replace("__DISCLAIMER__", escape(DISCLAIMER))
            .replace("__WHATIF_DATA__", json.dumps(whatif_data)).replace("__EV_DATA__", json.dumps(ev_data)))
    OUT.mkdir(exist_ok=True)
    (OUT / "static.html").write_text(html)
    (OUT / "hospital_template.xlsx").write_bytes(to_excel_bytes(h))
    (OUT / "power_plan.txt").write_text(plan_text(h, plan, rules))
    print(f"Wrote {OUT / 'static.html'} ({len(html) // 1024} KB, {len(whatif_data)} what-if combinations)")


if __name__ == "__main__":
    main()
