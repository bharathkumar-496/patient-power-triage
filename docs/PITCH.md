# Pitch — ENERGY SIMTECH'26, Track 3: Open Innovation

**Patient-to-Power Triage** — *"Every litre of diesel should reach the patient who can't wait."*

---

## A. 3-minute script (with demo clicks)

Split it across speakers. Times are targets.

**0:00 – 0:30 · The problem** *(Speaker 1, no slides needed — just the app open on "Live demo")*
> "It's night in a government hospital. The grid fails. The generator can
> carry only half the load. Someone has to decide what stays on — and today
> they decide from a fixed department list and memory. That list doesn't know
> that tonight, because the ICU is full, there are ventilated patients lying
> in general wards. After Hurricane Katrina, about 215 patients died in New
> Orleans hospitals and nursing homes, partly because generators failed.
> This is an **energy** problem: a limited amount of diesel and generator power,
> and a wrong decision about where it goes."

**0:30 – 1:15 · Today's way** *(Speaker 2 — "Today: fixed department list" selected)*
> "This is our simulated 200-bed hospital, floor by floor. Green circuits stay on,
> red are cut. Each dot is a high-need patient. **Red flashing dots are patients on
> life support with no power.** The fixed list kept empty operating theatres on,
> but cut the wards where ventilated patients are. 18 patients on life support
> have no power, and 44 kW of generator power goes to rooms with nobody in them."

**1:15 – 2:00 · Our plan** *(click "Our patient-aware plan")*
> "Our software knows which patient is on which device in which room, on which
> power line. It solves an optimisation in under a second. **All 52 life-support
> patients powered. Zero kW wasted.** It also tells staff exactly what to do:
> move these two patients out of the isolation ward — which isn't wired to the
> generator, a fault our pre-outage check finds — delay these two surgeries,
> switch off these circuits."

**2:00 – 2:30 · Things go wrong** *(turn on "Generator set 2 fails")*
> "Now half the generator fails. Our plan still powers 44 of 52 life-support
> patients — today's list would power 21. And the diesel lasts almost 17 hours."

**2:30 – 3:00 · Evidence and impact** *(open "Evidence (50 outages)")*
> "We tested 50 different outages against today's method. **42% fewer
> life-support patient-minutes without power. 81% fewer patients cut off at the
> start. Generator power wasted on empty rooms falls from 18% to 4%. 10% less
> diesel per hour — about ₹1,000 and 30 kg CO₂ every outage hour.** Never worse
> in any of the 50. It's free, open-source, needs no hardware, and works from an
> Excel sheet. Staff always make the final call."

---

## B. The six required sections (for slides / report)

### 1. Problem identification and significance
- Backup generators in many hospitals cannot carry the full load; diesel is
  limited and refuelling can take hours.
- Shedding is decided by a fixed department list, which doesn't know where
  life-support patients actually are tonight (ICU overflow into wards).
- Katrina: ~215 deaths in New Orleans hospitals and nursing homes; generator
  failure was part of the cause. Tijuana and Kassala (Sudan, April 2026) are
  **reported, disputed** cases — say so if you mention them.

### 2. Proposed solution and working principle
Software advisor linking **patient → device → room → circuit → generator**.
An OR-Tools optimisation chooses which circuits to keep and which patients to
move, under hard limits (generator 95%, breakers, beds, ICU-to-ICU only, a
powered lift for any cross-floor move), while maximising powered patient
priority and keeping load under a fuel-safe level from the generator's fuel
curve. Outputs: plan, move check, danger clock, what-if, pre-outage check.

### 3. Supporting evidence
50 simulated outages (generator 40–70% of demand, outage 2–24 h, staff's
outage guess ±30% wrong, random wiring faults):

| | Today's list | Our planner | Change |
|---|---|---|---|
| Life-support patient-minutes without power | 517,277 | 298,057 | **−42%** |
| Life-support patients cut off at start | 241 | 45 | **−81%** |
| Generator power wasted on empty loads | 18% | 4% | **−76%** |
| Full-blackout minutes (fuel ran out) | 9,677 | 7,029 | **−27%** |
| Diesel burn | 108.9 L/h | 97.6 L/h | **−10%** |
| Runtime per tank | 10.6 h | 11.9 h | **+1.3 h** |

Never worse in any of the 50. Still better on average with generator size and
fuel each changed ±20%. 31 automated tests confirm no hard rule is ever
broken. Full calculations: `docs/ASSUMPTIONS.md`.

### 4. Expected impact
- **Energy:** 11.3 L diesel saved per outage hour
- **Cost:** ≈ ₹1,000 per outage hour (₹90/L)
- **Emissions:** ≈ 30 kg CO₂ per outage hour
- **Safety:** 42% fewer life-support patient-minutes without power
- All from simulation, not a real hospital.

### 5. Feasibility, cost, scalability
- Python + OR-Tools + Streamlit: free, open-source, offline, any laptop
- No hardware. One-time cost: mapping beds to circuits (an electrician and a
  nurse, a few days — estimate)
- Excel upload or typed in; works with paper records
- Any hospital by swapping the tables; ~0.1 s per plan (≤ 1 s in hard cases)
- **Scale-up path:** add rooftop solar + battery to the same model so daytime
  outages burn even less diesel (future work, not built)

### 6. Innovation and sustainability
- Per patient, not per department; moves patients, not just cuts power
- Move check: the route must have power (the Tijuana lesson)
- Pre-outage check finds "this ward isn't really on backup" before it matters
- Less diesel and CO₂ per outage hour; no new hardware
- **Not claimed as new:** generator runtime prediction (prior art exists)

---

## C. Honest limits (say these before judges ask)
- Simulation with fake data; not tested in a real hospital
- Advisor only — staff make every decision
- Priority weights are examples; doctors must approve them
- Switching is per circuit, so patients are grouped by circuit
- Generic fuel curve; use the real generator's datasheet
- Total litres fall only 3.8%, because our generator keeps running longer
  (fewer blackouts); per running hour it burns 10% less
- In the ±20% sensitivity runs, 3 of 200 scenarios were worse than the fixed
  list (the outage guess was wrong)

## D. Q&A cheat sheet

| Question | Answer |
|---|---|
| Hospitals already have life-safety and critical branches by code. | Those are fixed when the building is wired. We adapt to *tonight's* patients, fuel and real wiring — and our pre-outage check finds where wiring doesn't match the code. |
| Who decides which patient matters more? | Doctors, in `rules.yaml`. The software applies their rules fast and consistently; staff confirm. |
| Moving ventilated patients is risky. | Only high-need patients, only into powered rooms, ICU patients only to ICU beds, cross-floor only with a powered lift, and the plan flags when manual bagging is needed during the move. |
| Where does the data come from? | Bed register + an electrician's circuit map, as Excel. Unknown devices are treated as life support until confirmed. |
| Why not just buy a bigger generator? | Costs lakhs and months; this costs almost nothing and also helps when a generator fails (what-if). |
| Is the simulation biased toward you? | Same generator, fuel and wrong outage guess for both; the baseline may skip and keep filling. We report ties (6/50), the 3/200 losses, and the small 3.8% total-litre saving. |
| What's the energy contribution? | Diesel goes to people, not empty rooms: wasted generator power 18% → 4%, 10% less diesel per hour, +1.3 h per tank. |
| In the failure demo, why is ICU bay A cut? | At 150 kW not everything fits. ICU patients may only move to ICU beds, and ICU bay B is full, so the planner keeps the circuits powering the most life-support patients. Bay A's patients show red on the danger clock so staff bring manual ventilation or a portable backup there first. Today's list would leave 31 patients unpowered, not 8. |
| How fast? | ~0.1 s for 186 patients; 5 s hard limit with a greedy fallback. |
| What about solar? | The same model can add solar + battery as another source — our scale-up plan. |

## E. Demo checklist (do this 10 min before)
1. `cd power-triage && .venv/bin/streamlit run app.py`
2. Open http://localhost:8501, browser full screen, zoom so the whole map fits
3. Start on **Live demo**, "Today: fixed department list", failure toggle **off**
4. Have Evidence tab pre-loaded (click it once beforehand)
5. Backup: screenshots of each step in case the laptop fails
