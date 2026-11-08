# CANIS report framework

How to turn one CANIS inspection run into a report that store managers and safety staff can act on. It works for any run and any detector. It describes what the report must say and where each fact comes from, so any script or person can build one.

A small worked example is in [`example/`](example/): [the input files](example/run/) and [the report they produce](example/expected_report.md). All of its data is invented.

## 1. Ground rules

1. **Logged data only.** Every number, status, photo and timestamp comes from the run folder. If a value was not logged, print `not measured`. Never estimate one.
2. **Models don't write facts.** Statuses, colours, zones and numbers come from fixed rules. A language model may only add the explanation described in section 7.
3. **No area is safe by default.** An area is `Low gamma` only if radiation was measured there and nothing else rules it out. It is a simulation flag, not an access decision.
4. **Show the misses.** Missed drums, false alarms and uninspected drums are always listed.
5. **Repeatable.** The same run folder always gives the same report. Sort everything, and use only the run's own timestamp.

## 2. Using it with any model or run

The report doesn't care which detector ran. To plug in a new one:

1. Map its classes to `normal`, `corrosion` and `bulge`.
2. Record each camera view of a drum as `{class: confidence}`.
3. Apply the decision rule and write `memory.json` in the format below.
4. Put the model name and weights hash in Technical details, and nowhere else in the report.

The default decision rule is below. If a run uses a different one, log it in `memory.json` as `rule` and print that in Technical details.

| Look | Result |
|---|---|
| Side look, 3 views | Fault in 2 or more views: `Confirmed defect`. Normal in 2 or more with no fault: `OK`. Otherwise a closer look. |
| Top-shelf drum | Always gets a closer look before a verdict |
| Closer look, 8 views in total | Fault in 4 or more, or in 3 and more than normal: `Confirmed defect`. Normal in 5 or more and fault in at most 1: `OK`. Nothing detected: `Couldn't inspect`. Otherwise `Suspect`. |

## 3. Input files

One folder per run. A field marked optional prints as `not measured` when it's missing.

**`memory.json`** (required)

| Field | Required | Meaning |
|---|---|---|
| `drums[]` | yes | One entry per drum (next table) |
| `started_utc`, `duration_s` | yes | Start time and length of the run |
| `detector`, `rule` | yes | Model name and decision rule, for Technical details |
| `yolo_calls`, `yolo_failures` | yes | Detector calls made and failed |
| `stills[]` | yes | `{t, kind, drum, file}` for each evidence photo |
| `expected_drums` | optional | Drums the run was sent to check. Defaults to the number of entries. |
| `aisle_length_m` | optional | So sections the robot never reached still appear |
| `dose_uSv`, `budget_uSv` | optional | Robot dose used and its budget |
| `run_id` | optional | Report number. Defaults to the run folder's name. |
| `aisle_start_x` | optional | Where section 0 m starts (the robot's start). Defaults to 1 m before the first stack. |
| `planted` | optional | `{drum_id: "rust"}` faults planted on purpose; printed as test notes. `HOT_FORCE_FAULTS` works too. |
| `cosmos_reviews`, `detector_sha256` | optional | Printed in Technical details |
| `report_tech` | optional | Extra `[label, value]` rows for Technical details (walk script, logged channels, …) |

**Each entry in `drums[]`**

| Field | Required | Meaning |
|---|---|---|
| `drum_id` | yes | Aisle, side, stack, tier, e.g. `A-L-03-T1` |
| `side`, `column`, `tier`, `x`, `y` | yes | Where it is |
| `status` | yes | `OK`, `Suspect`, `Confirmed defect` or `Couldn't inspect` |
| `finding`, `confidence` | yes | `none`, `corrosion`, `bulge` or both, and the best confidence |
| `views`, `fault_views`, `view_detail` | yes | Views taken, views showing a fault, and `{class: confidence}` per view |
| `category` | optional | `LLW` or `ILW`. Can be joined from the store inventory instead. |
| `dose_rate_at_drum_uSv_h`, `heat_rise_c`, `swab` | optional | Sensor readings at the drum |

**Other files**

| File | Required | Fields |
|---|---|---|
| `decisions.jsonl` | yes | `t`, `drum`, `kind`, `text`, `source` |
| `telemetry.jsonl` | yes | `t`, `pose` `[x, y, yaw]`, `phase`, `look`. Optional: `dose_rate_uSv_h`, `temperature_c`, `hydrogen_ppm`. |
| `detections.jsonl` | optional | One line per detector view: `t`, `drum`, `pass`, `faults`, `conf`. Use it for checking photos and decisions. |
| `stills/` | yes for flagged drums | Evidence photos. If one is missing, print `photo not logged`. |
| `colour_accuracy.json` | optional | From `scripts/hot/full_hall/wh_score_color.py`: per-drum truth and accuracy per drum colour. Used instead of `ground_truth.json` when present. |
| `video.json` | optional | `{summary, moments: [["0:00–0:13", "what it shows"], …]}` for the video evidence table |
| `ground_truth.json` | optional | `drums: {id: {rust, bulge}}` severities from 0 to 1. Never shown to the planner, and only used for section 5 of the report. |

## 4. From data to verdicts

**Plain words**

| Status | Report says | Colour |
|---|---|---|
| `Confirmed defect` | Action needed | Red |
| `Suspect` | Check again | Amber |
| `Couldn't inspect` | Check again, with the reason | Amber |
| `OK` | No problem found | Green |

Confidence prints as `High (88%)`: High from 70%, Medium from 50%, Low below that.

**Drum colour.** Start from the status above, then raise it if a sensor says so. "Above" means strictly above.

| Becomes | When |
|---|---|
| Red | Swab above 0.4 Bq/cm² alpha or 4 Bq/cm² beta/gamma; or a bulge with the surface at least 5 °C above air; or radiation at the drum above 100 µSv/h |
| Amber | Surface at least 5 °C above air with no visible fault |

**Area zones.** Split the aisle into 2 m sections and use the highest reading logged in each one. Take the first row that applies.

| Zone | When |
|---|---|
| Not checked | The robot logged nothing here |
| Keep out | Radiation above 100 µSv/h, or a bulging drum at least 5 °C above air |
| Restricted | Radiation above 7.5 µSv/h, or a red drum in the section. If radiation wasn't measured, add "this may need to be stricter". |
| Not checked | The robot walked here, but radiation wasn't measured |
| Low gamma | Radiation measured, below 7.5 µSv/h, and none of the above |

**Where the limits come from** (print these in the report)

| Limit | Source |
|---|---|
| 7.5 and 100 µSv/h | HSE, *Work with ionising radiation* (L121), regulation 17. Used here as instantaneous robot rules, which is not a legal controlled-area assessment. |
| Swab 0.4 and 4 Bq/cm² | IAEA SSR-6 Rev. 2 (2025), para 508, transport limits borrowed as escalation values |
| 5 °C above air | Team demo rule, not an operational limit |
| Hydrogen | No level set yet. Print the readings and "no cited alarm level". Hydrogen does not change any zone. |

**What to do** (fixed text, always printed)

| Finding | Action |
|---|---|
| Bulge, temperature not measured | Limit access to this aisle. Ask an engineer to assess the drum for pressure build-up, and measure its surface temperature (not measured in this inspection). |
| Bulge, at least 5 °C above air | Keep people out of this aisle section. Isolate the drum and get an urgent engineering assessment. |
| Bulge, no heat rise | Limit access to this aisle. Ask an engineer to assess the drum. Inspect again at the next round. |
| Rust | Ask an engineer to assess how far the rust has gone. Take a surface wipe if none was taken. Consider placing the drum in an overpack (a larger outer drum). |
| Failed swab | Keep people out. Contamination control and a survey by a qualified person. |
| Suspect | Inspect again within 7 days, with a closer look and a surface wipe (swab). |
| Couldn't inspect | Inspect again once the area is clear and radiation is back to normal. |
| Heat only | Measure again and check for gas generation. |

## 5. What the report contains, in order

Built by `tools/full_hall_report/report/build_report.py` (see its [README](../../tools/full_hall_report/report/README.md)): HTML for screen, A4 PDF for print, `summary.json` for machines. A4 portrait. Every page has a mono footer with the report number, "Practice run in a simulated store. Not for operational use." and page n / N. Sections start on a new page except where noted.

| # | Section | Contents |
|---|---|---|
| — | **Page 1: verdict and actions** | Dark band: dog-head mark, C.A.N.I.S. wordmark, "Containment Analysis & Nuclear Intelligence System", "Drum Store Inspection Report"; report number, store, start time on the right; yellow rule under it. Then the **verdict** in one sentence ("8 drums need action. 28 showed no problem.") with a second line for the aisle ("3 aisle sections restricted; 6 not checked. Radiation was not measured…"). A results bar split red / amber / green. Eight key numbers: drums checked X / Y, action needed, check again, no problem found, peak gamma, aisle sections, robot dose, mission time (unmeasured ones show `n/m`). **What to do now**: every red and amber drum, most urgent first, with result, what was seen and the fixed action. **This inspection**: store, report, start, mission time, robot, drums in scope, report software, status. Notes: what was not measured on this round; faults planted on purpose. |
| 01 | Aisle survey | Plan of each aisle: 2 m sections from where the robot started, shaded by rating (hatched = not walked); racks folded out flat on both sides, one cell per drum coloured by result, shelf nearest the aisle = bottom; stack numbers; planted faults marked; route with start and end; 1 m scale. Legend. Then one row per section: aisle, section, rating, peak gamma, peak H₂, samples, why. A sensor column is left out when the round never carried that sensor, and the note says so. |
| 02 | Every drum at a glance | Follows 01 on the same page if it fits. Worst first: drum (+ `planted` tag), waste (LLW / ILW), where (side, stack, shelf), result, what was seen, how sure, fault views (e.g. 3/3, 7/8), gamma at drum if measured. Note: how to read "how sure", fault views, drum names, waste colours, and "first inspection" (or the change since last time). |
| 03 | Drums that need attention | One block per red or amber drum, two or three per page: ID, plain location and waste class, result chip. Left: the evidence frame (the robot's overlay as recorded, or the detector's box drawn on the raw frame), caption with time / frame / body pitch, and a strip of the other views. Right: what was seen, how sure, views, why this rating, the readings that were measured, one "Not measured" line for the rest, surface wipe, label read, test note for a planted fault, **what the robot did** (each logged step with its time; Cosmos reasons quoted), and the **What to do** box. |
| 04 | Drums with no problem found | Best view of each green drum, when the run saved one. Left out when no green drum has a photo. |
| 05 | What this report cannot tell you | Uninspected drums with the reason; sections walked without a radiation reading and sections not walked; every sensor not measured anywhere. **How accurate was the robot?**: found / missed / false alarms, a table of missed drums with their simulated damage, and accuracy per drum colour with 95% ranges when `colour_accuracy.json` exists ("not made" when there is no truth). **How the ratings were made**: detector / rules / Cosmos Reason 2 / report, what each does and never does, and the count of Cosmos reviews by choice. **Limits used** with sources. **How to read the labels.** Simulation note and WPS/640. **Video evidence** (the cut's moments) when `video.json` exists. |
| A | Readings over time | Every logged sensor trace against the mission clock (gamma with the 7.5 / 100 lines), yellow lines at Cosmos decisions. When no sensor was carried, the route: distance along the aisle against time, red dots where a drum was found to need action. |
| B | Step-by-step record | Follows A. Every logged event: time, drum, source (CANIS rules / Cosmos Reason 2 / label reader), what happened in plain words, latency. Cosmos text is quoted exactly as logged. |
| C | Technical details | Report, run folder (last three path parts only), input format, report software, detector and weights SHA-256, decision rule, detector calls, Cosmos reviews, planted faults, ground-truth seed, logged channels, simulator, status names. Then every evidence frame: drum, view, time, frame, class, confidence, pitch, input SHA-256 or file. |

If there is a previous inspection, add "change since last time" to section 02. Otherwise say "first inspection".

## 6. Style

- **Type:** IBM Plex Mono for every label, heading, number, drum ID, table, chip and timestamp; IBM Plex Sans only for sentences (verdict, actions, reasons, quotes). Both are embedded, so the PDF looks the same offline.
- **Brand:** the console's dog-head mark and white wordmark on the ink band (`#111315`) with a yellow (`#f1c543`) rule; the name is written out once, on the cover, as *Containment Analysis & Nuclear Intelligence System*. Yellow is the brand colour only (band, section numbers, Cosmos tags, decision lines), never a status.
- **Colour:** red / amber / green only for drum results and aisle ratings; grey or hatched for not checked. Everything else is ink and grey.
- **Numbers:** right-aligned, tabular figures; units in lower case even in upper-case headers (µSv/h, ppm); `not measured` in light grey, never 0, never estimated.
- **Plain words:** "Left 3 · top shelf", not coordinates; "Action needed", not status codes; "How sure: High (96%)", not raw scores. Model names, hashes and file names appear only in Technical details and the record's source column.
- **Evidence:** every flagged drum shows the frame the verdict came from. The run's own overlay is shown as recorded; otherwise the detector's own box is drawn on the raw frame.
- Name only CANIS. Call the robot body "the quadruped" if it needs a name, and mention no other robot or vendor.
- Cite NDA WPS/640, *Guidance on Monitoring of Waste Packages During Storage*, by title only. Its clause numbers have not been checked.

## 7. Optional: written explanations

A language model may add a short explanation for red drums only, shown in quotes and labelled as a model explanation. Give it only that drum's logged facts. Every number in its answer must appear in those facts, and its fault must match the logged finding. If a check fails or the model is unreachable, print "explanation unavailable". If no model was used, Technical details says so.

## 8. Checklist before sharing

- [ ] Every drum in `memory.json` appears in section 2 with the right colour.
- [ ] The totals in the summary match the logs.
- [ ] **Open every evidence photo. The drum ID on the photo must match the drum it is filed under.**
- [ ] Photos come from the moment of the view, not the moment of the verdict. A robot may already have moved on by then.
- [ ] If a drum's verdict used fewer views than the rule says, the report says how many it used.
- [ ] No section is `Low gamma` without a radiation reading, and every `Not checked` section is listed.
- [ ] Hydrogen shows a cited level or "no level set yet".
- [ ] Missed drums and false alarms are listed.
- [ ] Building it twice gives the same content.
- [ ] No secrets, tokens or service URLs anywhere in the report.
