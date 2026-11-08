---
name: canis-run-report
description: Build the CANIS post-run inspection report (a professional PDF plus the HTML view) from one robot run's logged files. Use at the end of every CANIS / Spot patrol in the agentverse26 repo, or when asked to make, fix or re-run "the robot's report", "the inspection report", "the run PDF" or "the safety verdict per area".
---

# CANIS run report

After every run, the dog produces one report that says three things: **which drums need action**, **where the simulated survey found readings or issues that warrant review**, and **the evidence behind every claim**. The report is built only from files the run logged. No model writes facts into it.

## 0. Ground rules (read first)

1. **Logged data only.** Every number, status, photo and timestamp comes from the run folder. If a value wasn't measured, print `not measured`. Never estimate or fill one in.
2. **The model can't invent facts.** Cosmos Reason 2B writes free text in one place only: the "context" paragraph for each red drum (section 3). Its input is that drum's logged readings. Its output is shown in quotes, labelled "Cosmos explanation", and the builder checks it (step 5). Everything else (statuses, zones, tables, numbers) is computed by deterministic Python.
3. **No area is "safe" by default.** Without a logged gamma reading, report `NOT CHECKED` unless other evidence warrants escalation. Report `LOW GAMMA` only when readings are below the demo threshold and no nearby unresolved finding needs review. These labels do not clear access.
4. **Re-runnable.** The same run folder always gives the same PDF: sorted output, and the only timestamp is the run's own.
5. **Work inside the repo's report folders.** New code goes in `tools/full_hall_report/` (extend `report/`: add a loader for a new log format, don't fork the builder). Don't edit the detector, Cosmos, safety or sim code; import from them. Never commit secrets.

## 1. Inputs (one run folder)

`out/full_hall/<RUN_ID>/` (a `canis_walk/` folder from `out/hot/...` works the same way):

| File | Used for |
|---|---|
| `memory.json` | final status per drum, best evidence frame + box, dose rate there, looks, reason; `dose_uSv`, `budget_uSv` |
| `detections.jsonl` | every YOLO box: class, confidence, box, drum ID, distance |
| `decisions.jsonl` | every decision: time, drum, action, reason (Cosmos text) |
| `telemetry.jsonl` / `log.jsonl` | position over time, `dose_rate_uSv_h`, `temperature_c`, `relative_humidity_pct`, gas (`hydrogen_ppm`), thermal findings, swab results |
| `events.json`, `route.json` | spikes, blocks, route |
| `ground_truth.json` | **self-check only**; never shown to the planner and never used for statuses |
| `stills/`, `full_hall.mp4` | evidence |
| `sim/drums.json` (repo) | drum ID, category (LLW/ILW), position, aisle |

First, list which fields this run actually has. A sensor that's missing (e.g. no H2 channel, no swab taken) shows as `not measured` in every table that uses it.

## 2. Who does what (put this in the report's method box)

| Part | Job | Never does |
|---|---|---|
| **YOLO26s** (`yolo26s_20261107T225757Z_d625ef`, cut-off 0.25) | Draws boxes: `drum`, `corrosion`, `bulge`, each with a confidence | Decide status or safety |
| **Our rules** (Python, below) | Turn boxes + sensor readings into a **drum colour** (red / amber / green) and an **area zone** (low gamma / restricted / keep out / not checked) | Use free text |
| **Cosmos Reason 2B** | For each **red** drum, explains the context: what the fault is, how severe, what to do next | Change a colour, a zone or a number |
| **Report builder** | Assembles the PDF from the logs | Write any fact that isn't in the logs |

## 3. Drum colour rules

Use the run's final status from `memory.json`, then raise the colour using the sensors:

| Colour | When |
|---|---|
| **RED** | Status `Confirmed defect` (corrosion or bulge confirmed), OR swab above 0.4 Bq/cm² alpha or 4 Bq/cm² beta/gamma, OR bulge + drum surface ≥ 5 °C above air (the two-cue pressure screen), OR dose at the drum > 100 µSv/h |
| **AMBER** | Status `Suspect` or `Couldn't inspect`, OR drum surface ≥ 5 °C above air with no visible fault, OR residue seen but no swab taken |
| **GREEN** | Status `OK` and none of the above |

"Above" means strictly above: a value exactly on a limit isn't over it. `Couldn't inspect` is never green; always show the reason (dose spike, blocked, out of budget).

## 4. Aisle survey ratings

Split each aisle into **2 m sections** along its length, using the drum positions from `drums.json`. For each section, take the **highest** logged value while the robot was in that section:

| Zone | Rule (any one triggers it) |
|---|---|
| **KEEP OUT** | gamma > **100 µSv/h** (hot spot), OR a failed swab (above the limits in section 3), OR H2 ≥ **H2 alarm**, OR a RED bulge + heat drum (possible pressurisation) |
| **RESTRICTED** | gamma > **7.5 µSv/h** (controlled-zone level), OR a RED drum in the section, OR any drum ≥ 5 °C above air, OR H2 ≥ **H2 warning**, OR an AMBER drum with a suspected leak and no swab |
| **LOW GAMMA** | gamma measured, below the demo threshold, and no unresolved nearby finding |
| **NOT CHECKED** | the robot logged no readings there (blocked, skipped, out of budget) |

For each section print the zone, the reason ("gamma 142 µSv/h at 00:04:12"), and the readings it was based on.

**Where the numbers come from** (copy into the report's Limits section):
- **7.5 and 100 µSv/h:** HSE L121 (IRR17 ACOP), regulation 17, paragraphs 297–298. 7.5 µSv/h averaged over a working day is used for controlled-area designation; instantaneous readings above 100 µSv/h are discussed there. We use both as **instantaneous robot rules**. That isn't a legal controlled-area assessment. (Repo: `docs/inspection_source_register.md`.)
- **Swab limits 0.4 / 4 Bq/cm²:** IAEA SSR-6 Rev. 2 (2025), paragraph 508, the transport limits for non-fixed surface contamination. We borrow them as escalation values.
- **+5 °C above air:** the team's demo rule (`docs/sensors_and_criteria.md`, the two-cue pressure screen). Not an operational limit.
- **H2:** the team docs set **no alarm level** for hydrogen. Don't make one up. The proposal is to set it from hydrogen's lower flammable limit (LFL, 4% by volume in air): **warning = 10% LFL (0.4% vol, 4,000 ppm)** and **alarm = 25% LFL (1% vol, 10,000 ppm)**, the usual two-level setting on flammable-gas detectors. ⚠️ **Before using these, a person must cite a checked source** (e.g. HSE's flammable gas detector guidance, or BS EN 60079-29-2) and write it into `docs/inspection_source_register.md`. Until then, the report prints the H2 readings and says "H2 alarm level: not yet set (no cited source)", and H2 doesn't change any zone.

## 5. Cosmos explanations (red drums only)

For each RED drum, call the repo's existing Cosmos client (don't write a new one). Pass only that drum's logged facts: ID, category, YOLO classes and confidences, looks, dose there, temperature rise, swab, H2 nearby, and the evidence still. Ask for JSON:
`{"fault": ..., "severity": "low|medium|high", "context": <2 sentences>, "next_step": <1 sentence>}`.

Then **check** the answer:
- Every number in `context` must appear in the input facts.
- `fault` must match the logged class (corrosion / bulge / both).

If a check fails, or Cosmos is unreachable, print "Cosmos explanation unavailable" and use the fixed next step from section 7. Never print a failed answer. Save prompts and answers to `report/cosmos_explanations.jsonl` so they're traceable.

## 6. The PDF

Build it with the shared builder; don't write a new one:

```bash
python3 tools/full_hall_report/report/build_report.py <run_dir> [--store "Warehouse v3, aisle A (simulated)"] [--aisle-start 1.0 --aisle-length 18]
```

It writes `index.html`, `CANIS_report_<RUN_ID>.pdf` (A4, Playwright/Chromium), `summary.json` and `evidence/` from the same data. Rules: `report/rules.py`. A loader per log format: `report/loaders.py` (framework / warehouse walk folders, and `canis.v1` takes). Layout: `report/render.py` + `style.css`. Setup and agent steps: `tools/full_hall_report/report/README.md` and `IMPLEMENTING.md`.

**Page order, contents and style are specified in [`docs/report_framework/README.md`](../../../docs/report_framework/README.md), sections 5 and 6.** In short: page 1 is the verdict, results bar, eight key numbers, the "What to do now" list and run facts; then 01 aisle survey (plan + section table), 02 every drum at a glance, 03 drums that need attention (frame + readings + what the robot did + what to do), 04 green-drum photos if any, 05 what this report cannot tell you (gaps, accuracy, method, limits, label key, video), A readings or route over time, B step-by-step record, C technical details with every evidence frame. IBM Plex Mono for labels, numbers, IDs and tables; IBM Plex Sans for sentences; the dog-head mark and wordmark on an ink band with a yellow rule; red / amber / green only for status. The name is written out as *Containment Analysis & Nuclear Intelligence System*. Gamma at a drum sets the AREA zone, not the drum colour (otherwise every drum in a hot store turns amber).

Reference outputs: `tools/full_hall_report/report/example/`: the 36-drum showcase walk (083203) and the adaptive-aisle take (112205). The older LaTeX builders (`build_walk_report.py`, `pdf/`) are kept for reference only.

## 7. Fixed recommended actions (used when there's no Cosmos text, and always printed as well)

| Finding | Action |
|---|---|
| Bulge confirmed (+ heat) | Keep out of the section; isolate the drum; arrange an engineering assessment for pressurisation |
| Bulge confirmed (no heat) | Restrict access; engineering assessment; re-inspect at the next round |
| Corrosion confirmed | Engineering assessment of container integrity; swab if one wasn't taken; consider overpacking |
| Failed swab | Keep out; contamination control and survey by a qualified person |
| Suspect | Re-inspect within 7 days (closer look, swab) |
| Couldn't inspect | Re-inspect when the cause is cleared (dose normal / aisle clear) |
| Heat anomaly only | Re-measure; check for gas generation |

## 8. Run it automatically

Add a final step to the end-of-run script (e.g. `scripts/hot/full_hall/full_hall_round.py`, or wherever the run finishes) that calls:

```bash
python tools/full_hall_report/report/build_report.py out/full_hall/<RUN_ID>
```

If the report fails, the run still counts. Log the error to `report/report_error.txt` and exit non-zero from the report step only.

## 9. Check before you hand it over

- [ ] Every number in the PDF matches the run files (spot-check 5 drums and 3 areas).
- [ ] Every flagged drum has a photo with its YOLO box on it.
- [ ] Low gamma requires a logged gamma reading and no unresolved nearby finding. Include areas without readings.
- [ ] H2 shows a cited level, or "not yet set (no cited source)".
- [ ] Cosmos text appears only on red drums, quoted and labelled, and passed the number check.
- [ ] Running it twice gives the same PDF content.
- [ ] No secrets, tokens or Modal URLs in the PDF.

## Structure source

The register and findings follow the themes of NDA **WPS/640, Guidance on Monitoring of Waste Packages During Storage** (issue 02, March 2008): container condition, seals and filters, wasteform, store environment, a monitoring strategy and frequency, and records over time. ⚠️ The GOV.UK copy of WPS/640 returned "gone" (HTTP 410) on 8 Nov 2026, so its clause numbers haven't been checked. Cite the document by its title only, not by clause, until someone checks a copy.
