# Patient-to-Power Triage

*Power should reach the patient who can't wait.*

A software advisor for hospitals on backup power. It links every patient,
device, room and power circuit. When the generator can't carry everything, it
tells staff which circuits to keep, which to cut, who to move, which
surgeries to delay, and how long the diesel will last.

ENERGY SIMTECH'26 — Track 3: Open Innovation. **Simulated data only. Staff
make the final decision.**

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/streamlit run app.py          # dashboard at http://localhost:8501
.venv/bin/python -m sim.run_sim         # 50-outage simulation + sensitivity
.venv/bin/python -m pytest -q           # 31 safety and maths tests
.venv/bin/python -m data.generate       # rewrite data/hospital.xlsx
.venv/bin/python build_web.py           # build site/ (app runs in the browser via stlite)
npx vercel deploy site --prod           # publish site/ to Vercel
```

The web version runs the same `app.py` in the visitor's browser. OR-Tools can't
run there, so `engine/solver.py` uses SciPy's MILP solver instead (same plans;
checked on all 50 scenarios). `site/static.html` is an instant precomputed copy.

(No `uv`? Use `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.)

## Layout

| Path | What |
|---|---|
| `app.py` | Dashboard: Plan, Danger clock, What-if, Pre-outage check, Evidence, Data |
| `rules.yaml` | Device priorities and planner settings (example values) |
| `engine/` | Data model, fuel model, baseline, CP-SAT planner, danger clock, pre-check, what-if |
| `data/` | Fake hospital generator and `hospital.xlsx` (also the upload template) |
| `sim/` | 50-scenario simulation and results CSVs |
| `tests/` | Hard-constraint and calculation tests |
| `docs/` | `ASSUMPTIONS.md`, `HOW_IT_WORKS.md`, `PITCH.md` |

## Headline result (simulation)

Against today's fixed department list, over 50 simulated outages:
**−42%** life-support patient-minutes without power, **−81%** life-support
patients cut off at the start, generator power wasted on empty loads cut from
**18% to 4%**, **−10%** diesel burn per hour, **+1.3 h** runtime per tank.
Never worse in any of the 50 main scenarios. See `docs/ASSUMPTIONS.md`.
