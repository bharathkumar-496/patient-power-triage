"""Visual pieces for the dashboard: styling, KPI cards and the hospital map."""
from __future__ import annotations

from html import escape

from engine.model import Hospital
from engine.plan import Plan, circuit_loads, patient_status

FLOOR_NAMES = {3: "Floor 3 · Wards", 2: "Floor 2 · Wards", 1: "Floor 1 · Theatres & ICU",
               0: "Ground · Emergency & services"}

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
.pt-hero {background: linear-gradient(135deg,#0f3d3e,#0f766e); color:#fff; border-radius:16px;
          padding:18px 24px; margin-bottom:14px;}
.pt-hero h1 {color:#fff; margin:0; font-size:2rem;}
.pt-hero p {margin:4px 0 0; opacity:.9;}
.pt-cards {display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:6px 0 14px;}
.pt-card {background:#fff; border:1px solid #e3e8ef; border-radius:14px; padding:14px 16px;
          box-shadow:0 1px 2px rgba(0,0,0,.04);}
.pt-card .lbl {font-size:.8rem; color:#5b6573; text-transform:uppercase; letter-spacing:.03em;}
.pt-card .val {font-size:1.9rem; font-weight:700; color:#111827; line-height:1.2;}
.pt-card .sub {font-size:.85rem; color:#5b6573;}
.pt-card.good {border-left:6px solid #16a34a;} .pt-card.bad {border-left:6px solid #dc2626;}
.pt-card.warn {border-left:6px solid #f59e0b;} .pt-card.info {border-left:6px solid #0f766e;}
.pt-floor {margin:8px 0 4px; font-weight:600; color:#334155; font-size:.9rem;}
.pt-row {display:flex; flex-wrap:wrap; gap:8px;}
.pt-tile {border-radius:10px; padding:8px 10px; min-width:118px; flex:1 1 118px; max-width:190px;
          border:2px solid transparent; font-size:.78rem; color:#111;}
.pt-tile .nm {font-weight:600; line-height:1.15;}
.pt-tile .kw {color:#374151; font-size:.72rem; margin-top:2px;}
.pt-keep {background:#dcfce7; border-color:#86efac;}
.pt-cut {background:#fee2e2; border-color:#fca5a5; opacity:.85;}
.pt-off {background:#e5e7eb; border-color:#9ca3af; background-image:repeating-linear-gradient(45deg,transparent 0 6px,rgba(0,0,0,.05) 6px 12px);}
.pt-dots {margin-top:5px; line-height:12px;}
.pt-dot {display:inline-block; width:11px; height:11px; border-radius:50%; margin:0 2px 2px 0;}
.pt-ok {background:#16a34a;} .pt-risk {background:#dc2626; animation:pt-pulse 1s infinite;}
.pt-mid {background:#9ca3af;} .pt-moved {box-shadow:0 0 0 2px #2563eb;}
@keyframes pt-pulse {0%,100%{opacity:1; transform:scale(1)} 50%{opacity:.35; transform:scale(1.3)}}
.pt-legend {font-size:.8rem; color:#475569; margin:6px 0 10px;}
.pt-legend span {margin-right:14px; white-space:nowrap;}
.pt-move {background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:8px 12px;
          margin:4px 0; font-size:.88rem; color:#1e3a8a;}
.pt-foot {font-size:.8rem; color:#64748b; margin-top:16px;}
</style>
"""


def cards(items) -> str:
    """items: (label, value, sub, tone) with tone in good/bad/warn/info."""
    html = "".join(f'<div class="pt-card {t}"><div class="lbl">{escape(l)}</div>'
                   f'<div class="val">{escape(v)}</div><div class="sub">{escape(s)}</div></div>'
                   for l, v, s, t in items)
    return f'<div class="pt-cards">{html}</div>'


def hospital_map(h: Hospital, plan: Plan, rules: dict) -> str:
    loads = circuit_loads(h, plan, rules)
    pts = patient_status(h, plan, rules)
    pts = pts[pts["weight"] >= 40]
    html = []
    for floor in sorted(loads["floor"].unique(), reverse=True):
        html.append(f'<div class="pt-floor">{escape(FLOOR_NAMES.get(floor, f"Floor {floor}"))}</div>'
                    '<div class="pt-row">')
        for _, c in loads[loads["floor"] == floor].sort_values("id").iterrows():
            cls = "pt-keep" if c["kept"] else ("pt-off" if not c["on_backup"] else "pt-cut")
            state = "ON" if c["kept"] else ("NO BACKUP" if not c["on_backup"] else "CUT")
            here = pts[pts["circuit_id"] == c["id"]]
            dots = []
            for _, p in here.sort_values("weight", ascending=False).iterrows():
                tone = ("pt-ok" if p["powered"] else "pt-risk") if p["life_support"] else "pt-mid"
                moved = " pt-moved" if p["moved"] else ""
                tip = escape(f"{p['id']} {p['name']} - {p['devices']}"
                             f"{' (moved here)' if p['moved'] else ''}")
                dots.append(f'<span class="pt-dot {tone}{moved}" title="{tip}"></span>')
            kw = f"{c['base_kw'] + c['device_kw']:.0f} kW · {state}"
            html.append(f'<div class="pt-tile {cls}" title="{escape(c["id"])}">'
                        f'<div class="nm">{escape(c["name"])}</div><div class="kw">{kw}</div>'
                        f'<div class="pt-dots">{"".join(dots)}</div></div>')
        html.append("</div>")
    legend = ('<div class="pt-legend"><span>🟩 kept on generator</span><span>🟥 cut</span>'
              '<span>▨ not wired to generator</span>'
              '<span><span class="pt-dot pt-ok"></span>life support, powered</span>'
              '<span><span class="pt-dot pt-risk"></span>life support, NO power</span>'
              '<span><span class="pt-dot pt-mid"></span>other high-need patient</span>'
              '<span><span class="pt-dot pt-ok pt-moved"></span>moved here</span></div>')
    return legend + "".join(html)
