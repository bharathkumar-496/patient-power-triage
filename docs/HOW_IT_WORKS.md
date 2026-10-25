# How it works — for every team member

Read this before the presentation. Each of you should be able to explain any
box below in your own words.

```
 Excel / fake data ──► model.py ──► planner.py ──► Plan ──► dashboard (app.py)
                          │            ▲                        │
                          │       rules.yaml                    ├─ danger clock
                          ├──► precheck.py                      ├─ what-if
                          └──► baseline.py (today's way)        └─ evidence (sim)
```

## 1. The data (`engine/model.py`, `data/generate.py`)

Five tables, the same shape whether from Excel or the fake hospital:

- **circuits** — the power lines. Each has a load (kW), a breaker limit, and
  whether it is actually wired to the generator (`on_backup`).
- **rooms** — which circuit feeds each room, beds, who can be cared for there.
- **patients** — who is in which room and on which devices.
- **surgeries** — which theatres have a surgery running or waiting.
- **generator** — size, diesel, expected outage, when the tanker comes.

`patient_needs()` turns a patient's device list into kW, priority weight,
life-support yes/no and battery minutes, using `rules.yaml`.

## 2. Today's way (`engine/baseline.py`)

A fixed department list: fire → theatres → ICU → NICU → ER → … → admin.
Keep circuits in that order until the generator is 95% full. It does not
know a ventilated patient is in a general ward, never moves anyone, and
ignores fuel. This is what we beat.

## 3. Our planner (`engine/planner.py`)

An optimisation model solved by Google OR-Tools CP-SAT (free, open source).

- **Yes/no decisions:** keep each circuit? Move each high-priority patient
  to which free bed?
- **Rules it can never break:** generator ≤ 95%; breakers; beds; neonates only
  to NICU/maternity; no moving patients in surgery or on dialysis; theatres
  with surgery running stay on; circuits not wired to the generator can't be
  kept; **moving to another floor needs a lift that is powered** (the move
  check); patients only move into rooms that stay powered.
- **What it tries to maximise:** the sum of priority weights of powered
  patients + value of things like the oxygen plant and blood bank − a small
  cost per kW of diesel − a bigger penalty for load above the "fuel-safe"
  level − a penalty per move.

Because a ventilated patient is worth 100 and a ward circuit costs only
~8 kW × 1.6 ≈ 13 points, the planner always tries to power life support
first, then sheds low-value loads (admin AC, laundry, empty theatres) to save
diesel. It solves in about 0.1 s for our 186-patient hospital (up to ~1 s in hard what-if cases).

If the essential load is bigger than the generator, it falls back to a
simple greedy plan and says so.

## 4. Danger clock (`engine/danger_clock.py`)

For each patient: minutes until their device has no power.
Cut circuit → device battery only. Kept circuit → until the diesel runs out
(or "safe" if the tanker arrives first). Red < 30 min, amber < 2 h.

## 5. Pre-outage check (`engine/precheck.py`)

Run on a normal day. Flags: life-support patients on circuits not on the
generator; lifts not on backup; no powered evacuation route; theatres not on
backup; overloaded circuits; devices with little battery; diesel that will
run out before the tanker; missing data. Each has a fix in plain words.

## 6. What-if (`engine/whatif.py`)

Copies the hospital and makes things worse: lose generator capacity, lose
fuel, longer outage, late tanker. Then re-plans so you can compare.

## 7. Simulation (`sim/run_sim.py`)

50 different nights. For each, plan with both methods using the *expected*
outage, then score against the *actual* outage minute by minute: who loses
power, for how long beyond their battery, when the diesel runs out, how much
diesel is burned. Sensitivity runs repeat this with generator size and fuel
±20%.

## 8. Tests (`tests/test_engine.py`)

31 automatic checks that the planner never breaks a hard rule, that the fuel
maths matches a hand calculation, and that the pre-outage check catches
injected faults. Run: `.venv/bin/python -m pytest -q`.
