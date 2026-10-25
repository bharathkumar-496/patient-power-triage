# Assumptions and calculations

Every number below is an **assumption** for the simulation, not a measured
fact from a real hospital. Check each against a real datasheet or hospital
before quoting it as fact. Where a value came from a known source, the source
is named — verify it before presenting.

## 1. Diesel generator fuel model

Linear "Willans line" fuel curve with the default coefficients used by the
HOMER Pro microgrid software (source: HOMER documentation — verify):

```
fuel (L/h) = 0.08145 × rated kW  +  0.246 × load kW
```

The first term is fuel burned just to keep the engine turning; the second
grows with load. This is why cutting unnecessary load saves diesel but never
brings consumption to zero.

**Worked example** (300 kW generator, 800 L of diesel):

| Plan | Load | Burn rate | Runtime |
|---|---|---|---|
| Fixed list (today) | 279.8 kW | 0.08145×300 + 0.246×279.8 = **93.3 L/h** | 800 ÷ 93.3 = **8.6 h** |
| Patient-aware plan | 275.5 kW | 0.08145×300 + 0.246×275.5 = **92.2 L/h** | 800 ÷ 92.2 = **8.7 h** |

In this scenario the fuel saving is small. The big difference is *who* is
powered: 52/52 life-support patients vs 34/52 (see section 5).

**Fuel-safe load.** If the diesel must last `H` hours, the largest load is
`(fuel ÷ H − 0.08145 × rated) ÷ 0.246`. The planner aims for `H` =
min(expected outage, tanker arrival) × 1.10 (10% reserve) and pays a
penalty for every kW above it.

## 2. Emissions and cost

| Value | Used | Note |
|---|---|---|
| CO₂ per litre of diesel | 2.68 kg | Standard combustion factor — verify |
| Diesel price | ₹90 / L | Assumed; update to the local pump price |

## 3. Fake hospital

200-bed government district hospital, 4 floors, 33 circuits, 2 bed lifts.

| Load | kW (assumed) |
|---|---|
| Admin AC | 30 |
| Kitchen | 35 |
| Laundry | 40 |
| CT & X-ray | 60 |
| MRI chiller | 25 |
| PSA oxygen plant | 30 |
| Each operating theatre | 22 |
| Each ICU bay | 14 |
| NICU | 10 |
| Each general ward (lights, fans) | 8 |
| Each corridor AC | 15–18 |
| Each bed lift | 15 |
| **Total normal demand** | **≈ 614 kW** (incl. ~33 kW of patient devices) |

Injected real-world problems: ventilated patients in general wards because
the ICU is full (ICU overflow); O₂ concentrators in wards; lift B and the
isolation ward not wired to the generator.

## 4. Devices (rules.yaml — example values, need doctor approval)

| Device | kW | Battery (min) | Weight | Life support |
|---|---|---|---|---|
| Ventilator | 0.25 | 30 (30% of units: 0) | 100 | yes |
| Incubator / warmer | 0.60 | 0 | 90 | yes |
| O₂ concentrator | 0.35 | 0 | 80 | yes |
| Inotrope syringe pump | 0.03 | 120 | 70 | yes |
| Dialysis machine | 1.50 | 0 | 60 | no |
| Suction | 0.20 | 0 | 40 | no |
| Monitor | 0.06 | 60 | 20 | no |
| Unknown device | 0.30 | 0 | 100 | yes (safe default) |

## 5. Simulation set-up (sim/run_sim.py)

| Parameter | Range (random, seeded) |
|---|---|
| Bed occupancy | 70–110% |
| ICU overflow | 10–25% of ICU beds |
| Generator size | 40–70% of normal demand |
| Tank size | 3.3 L per kW of rating (≈ 10 h at full load) |
| Fuel in tank | 40–100% |
| Actual outage | 2–24 h |
| Staff's expected outage | actual × 0.7–1.3 (staff guess wrong) |
| Diesel tanker arrives | 6–18 h |
| Wiring faults | lift B off backup 60%, isolation ward 50%, lift A 15%, ICU bay B 10% |

Both methods plan using the *expected* outage. They are scored on the
*actual* outage. A patient is harmed for every minute they are without
power beyond their device battery.

## 6. Results (50 scenarios, seeds 1000–1049)

| Metric (total over 50 outages) | Fixed list | Patient-aware | Change |
|---|---|---|---|
| Life-support patient-minutes without power | 517,277 | 298,057 | **−42%** |
| Life-support patients cut off from the start | 241 | 45 | **−81%** |
| …of them stranded upstairs with no lift | 217 | 45 | **−79%** |
| Minutes of full blackout (fuel ran out) | 9,677 | 7,029 | **−27%** |
| Generator power spent on empty, low-value loads* | 61.1 kW (18% of load) | 14.9 kW (4%) | **−76%** |
| Average generator load | 327 kW | 281 kW | −14% |
| Average diesel burn | 108.9 L/h | 97.6 L/h | **−10%** |
| Runtime per full tank | 10.6 h | 11.9 h | **+1.3 h** |
| Planned (calm) patient moves | 0 | 33 | — |
| Scenarios where planner was worse | — | **0 of 50** | better in 44, equal in 6 |

\* Circuits with no patients and value ≤ 10: empty theatres, offices, corridor
AC, laundry, kitchen, CT, unused lifts. Fire/exit lighting is never counted.

**Diesel saved per outage hour:** 108.9 − 97.6 = **11.3 L/h** →
≈ **₹1,017** and **30 kg CO₂** per hour of outage (at ₹90/L, 2.68 kg/L).

**Clinical rule added:** ICU patients may only be moved to another ICU bed,
never to a general ward. This costs a little (−42% instead of −44%) but keeps
the plan clinically sensible.

**Honest note on total litres.** Total diesel burned falls only 3.8%
(54,614 L → 52,525 L). That is because the planner's generator *keeps
running longer* — fewer blackouts — so it burns for more hours. Per hour
of running, it burns 10% less. Report both numbers.

**Honest note on emergency evacuations.** In many scenarios the tank runs dry
before the tanker arrives *whatever* plan is used, so most life-support
patients lose power at some point under both methods (1,588 vs 1,386 patient
cases). The planner reduces this, but fuel supply is the real fix — which is
why the pre-outage check flags "fuel runs out before refuel".

## 7. Sensitivity (each assumption ±20%)

Average per outage:

| Variant | LS patient-minutes (fixed → planner) | Blackout min | Burn L/h |
|---|---|---|---|
| Generator −20% | 14,426 → 7,301 | 194 → 175 | 86.6 → 83.1 |
| Generator +20% | 8,549 → 4,827 | 194 → 111 | 130.5 → 109.4 |
| Fuel −20% | 12,484 → 8,011 | 256 → 193 | 108.9 → 93.9 |
| Fuel +20% | 8,591 → 4,348 | 141 → 99 | 108.9 → 100.1 |

The planner wins on average in every variant, so the result does not depend
on one lucky assumption. Across these 200 extra scenarios it was worse than
the fixed list in **3** — cases where the staff's outage guess was wrong and
the planner shed load for an outage that turned out different. Say this if
asked.

## 8. What this does NOT prove

- It is a simulation with fake data, not a hospital trial.
- Real switching is at panel/circuit level and done by staff.
- Device weights are examples; doctors must set them.
- The fuel curve is generic; a real generator's datasheet may differ.
