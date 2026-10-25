"""Build the Vercel site: the real dashboard (app.py) running in the browser.

Vercel cannot run a Python server, so the site uses stlite: Streamlit +
Python (Pyodide) running inside the visitor's browser. Everything works as on
localhost - editing tables, uploading Excel, changing generator inputs and
re-planning live. OR-Tools cannot run in the browser, so engine/solver.py
switches to SciPy's MILP solver there (same model, same plans).

Also writes the instant-loading precomputed copy at site/static.html.

    .venv/bin/python build_web.py
    npx vercel deploy site --prod
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import export_static

ROOT = Path(__file__).parent
OUT = ROOT / "site"
STLITE = "https://cdn.jsdelivr.net/npm/@stlite/browser@1.10.0/build"
APP_FILES = ["app.py", "ui.py", "rules.yaml", "data/__init__.py", "data/generate.py",
             "sim/__init__.py", "sim/run_sim.py", "sim/results.csv", "sim/sensitivity.csv",
             *[f"engine/{p.name}" for p in sorted((ROOT / "engine").glob("*.py"))]]
REQUIREMENTS = ["pandas", "plotly", "pyyaml", "openpyxl", "scipy"]
THEME = {"theme.base": "light", "theme.primaryColor": "#0f766e", "theme.backgroundColor": "#f7f9fb",
         "theme.secondaryBackgroundColor": "#eef2f5", "theme.textColor": "#111827",
         "client.toolbarMode": "minimal"}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patient-to-Power Triage</title>
<meta name="description" content="Patient-aware backup power planning for hospitals - ENERGY SIMTECH'26 Track 3.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>">
<link rel="stylesheet" href="__STLITE__/stlite.css">
<style>
:root {color-scheme: light;}
body {margin:0; background:#f7f9fb; color:#111827; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
#loading {position:fixed; inset:0; display:flex; align-items:center; justify-content:center; padding:16px; z-index:2; background:#f7f9fb;}
#loading .box {max-width:520px; text-align:center;}
#loading h1 {margin:0 0 8px; color:#0f3d3e;}
#loading p {color:#475569; line-height:1.5;}
#loading a {color:#0f766e;}
.spin {width:42px; height:42px; border:4px solid #cbd5e1; border-top-color:#0f766e; border-radius:50%;
       margin:18px auto; animation:s 1s linear infinite;}
@keyframes s {to {transform:rotate(360deg);}}
#root {position:fixed; inset:0; z-index:1; overflow:auto;}
</style></head>
<body>
<div id="loading"><div class="box"><h1>⚡ Patient-to-Power Triage</h1><div class="spin"></div>
<p>Starting the full app inside your browser (Python + the planner).<br>
The first visit takes about 20–60 seconds; after that it is cached.</p>
<p>In a hurry? <a href="static.html">Open the instant read-only version</a>.</p></div></div>
<div id="root"></div>
<script type="module">
import { mount } from "__STLITE__/stlite.js";
const files = __FILES__;
mount({
  entrypoint: "app.py",
  requirements: __REQS__,
  files: Object.fromEntries(files.map(f => [f, {url: "app/" + f}])),
  streamlitConfig: __THEME__,
}, document.getElementById("root"));
// hide the loading screen once the dashboard has drawn its header
const t = setInterval(() => {
  if (document.querySelector(".pt-hero")) { document.getElementById("loading").remove(); clearInterval(t); }
}, 400);
</script>
</body></html>
"""


def main():
    if OUT.exists():  # keep Vercel's project link
        for f in OUT.iterdir():
            if f.name != ".vercel":
                f.unlink() if f.is_file() else shutil.rmtree(f)
    for rel in APP_FILES:
        dst = OUT / "app" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    html = (PAGE.replace("__STLITE__", STLITE).replace("__FILES__", json.dumps(APP_FILES))
            .replace("__REQS__", json.dumps(REQUIREMENTS)).replace("__THEME__", json.dumps(THEME)))
    (OUT / "index.html").write_text(html)
    print(f"Wrote {OUT / 'index.html'} with {len(APP_FILES)} app files")
    export_static.main()


if __name__ == "__main__":
    main()
