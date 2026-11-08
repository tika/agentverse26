# CANIS report framework

How to turn one CANIS inspection run into a report that store managers and safety staff can act on. It works for any run and any detector. It describes what the report must say and where each fact comes from, so any script or person can build one.

A small worked example is in [`example/`](example/): [the input files](example/run/) and [the report they produce](example/expected_report.md). All of its data is invented.

## 1. Ground rules

1. **Logged data only.** Every number, status, photo and timestamp comes from the run folder. If a value was not logged, print `not measured`. Never estimate one.
2. **Models don't write facts.** Statuses, colours, zones and numbers come from fixed rules. A language model may only add the explanation described in section 7.
3. **No area is safe by default.** An area is `Safe` only if radiation was measured there and nothing else rules it out.
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
| Safe | Radiation measured and none of the above |

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

A4 portrait. Every page has the report number in the header, and "Practice run in a simulated store. Not for operational use." with the page number in the footer.

| # | Section | Contents |
|---|---|---|
| - | Summary | Logo, store, date, report number, time taken. Summary box: drums checked X of Y, count per colour, count per zone, robot dose, one-sentence verdict. Key to the labels. |
| 1 | Who can go where | Plan of the aisle with drums, zones and the route, then one row per 2 m section with its zone and reason |
| 2 | Every drum at a glance | Worst first: drum, waste category, side and stack, shelf, result, what was seen, how sure |
| 3 | Drums that need attention | One block per red or amber drum: evidence photo with the box drawn on, what was seen, how sure, why, sensor readings, what the robot did with times, what to do |
| 4 | What was not checked | Uninspected drums with the reason, unmeasured sensors, and anything outside this round |
| 5 | How accurate was the robot? | From `ground_truth.json`: flagged, missed, false alarms, couldn't inspect. Say "not available" if there is no truth file. |
| 6 | How this report was made | Plain description of the method, the limits table, and a short "Please note" paragraph. No separate limitations section. |
| A | The robot's route over time | Distance along the aisle against time, with verdicts marked |
| B | Step-by-step record | Every decision in time order, in plain words |
| C | Technical details | Run ID, software version, walk script, model and weights hash, detector calls, decision rule, logged channels, status names |

If there is a previous inspection, add "change since last time" to section 2. Otherwise print "first inspection".

## 6. Style

- Written for people who aren't engineers: "Left, stack 3, top shelf", not coordinates. "Action needed", not status codes.
- Model names, run IDs and file names appear only in Technical details.
- Name only CANIS. Call the robot body "the quadruped" if it needs a name, and mention no other robot or vendor.
- Source Sans, black and grey. Red, amber and green only on labels.
- Cite NDA WPS/640, *Guidance on Monitoring of Waste Packages During Storage*, by title only. Its clause numbers have not been checked.

## 7. Optional: written explanations

A language model may add a short explanation for red drums only, shown in quotes and labelled as a model explanation. Give it only that drum's logged facts. Every number in its answer must appear in those facts, and its fault must match the logged finding. If a check fails or the model is unreachable, print "explanation unavailable". If no model was used, Technical details says so.

## 8. Checklist before sharing

- [ ] Every drum in `memory.json` appears in section 2 with the right colour.
- [ ] The totals in the summary match the logs.
- [ ] **Open every evidence photo. The drum ID on the photo must match the drum it is filed under.**
- [ ] Photos come from the moment of the view, not the moment of the verdict. A robot may already have moved on by then.
- [ ] If a drum's verdict used fewer views than the rule says, the report says how many it used.
- [ ] No section is `Safe` without a radiation reading, and every `Not checked` section is listed.
- [ ] Hydrogen shows a cited level or "no level set yet".
- [ ] Missed drums and false alarms are listed.
- [ ] Building it twice gives the same content.
- [ ] No secrets, tokens or service URLs anywhere in the report.
