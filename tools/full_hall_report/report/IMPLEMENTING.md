# Implementing the run report for your runs (agent instructions)

You are adding the C.A.N.I.S. post-run report to a run pipeline. Do the steps in order. Don't skip the checks in step 5.

## 0. Ground rules

1. **Don't fork the builder.** If your run logs a different format, add a loader (step 3). Don't copy `render.py` or `rules.py` into your own folder.
2. **Logged data only.** If your run did not log a value, the loader leaves it `None` and the report prints *not measured*. Never estimate, interpolate or default one.
3. **Rules change in one place.** Thresholds, colours, zones and actions live in `rules.py`, each with its printed source in `LIMITS`. Change them only if a person asks, and update the source text in the same edit.
4. **Models never write facts.** Planner or Cosmos text can appear only as a quoted, labelled `event` in the step-by-step record. It never sets a status, colour, zone or number.
5. **No secrets in the report.** No tokens, Modal URLs or truth labels. Ground truth only enters through `truth` (self-check) and must never be written into the robot's own logs.

## 1. Set up (once)

```bash
git fetch origin && git checkout claude/report-framework     # or main, once it is merged
cd tools/full_hall_report/report
npm install && npx playwright install chromium              # PDF step only
python3 -c "import PIL" || pip install pillow               # optional: smaller PDFs
```

Python 3.9+, no other Python packages. If Playwright is already installed elsewhere, set `PLAYWRIGHT_DIR=<folder whose node_modules has playwright>` instead of installing.

## 2. Build a report from a run folder

```bash
python3 tools/full_hall_report/report/build_report.py <run_dir> --out <run_dir>/report
```

`--format` is detected automatically:

| Your run folder has | Format | Loader |
|---|---|---|
| `report.json` + `log.jsonl` + `evidence/` (warehouse-v3 adaptive-aisle takes, `schema: canis.v1`) | `canis.v1` | `load_canis_v1` |
| `memory.json` + `telemetry.jsonl` + `decisions.jsonl` (+ `stills/`, `colour_accuracy.json` or `ground_truth.json`, `video.json`): the framework contract and the warehouse-v3 walk folders (`canis_wh_full_cosmos`) | `framework` | `load_framework` |

If one of those already matches, skip to step 4. To check that the builder works, run it on the invented example first:
`python3 tools/full_hall_report/report/build_report.py docs/report_framework/example/run --out /tmp/canis-example --no-pdf`
Its `summary.json` must match `docs/report_framework/example/expected_report.md`: 2 action needed, 2 check again, 2 no problem; sections 0–2 m restricted, 2–4 m low gamma, 4–6 m keep out, 6–8 m not checked.

## 3. Add a loader for a new log format

Add `load_<name>(run: Path) -> dict` to `loaders.py`, register it in `load()` and `detect()`, and add it to `--format` choices in `build_report.py`. It must return this run model (`None` for anything not logged):

```python
dict(
  id='<run id>', note=None,               # note: shown in a box on page 1 (e.g. "invented data")
  started='<UTC timestamp>' or None, duration_s=float or None,
  dose_uSv=float or None, budget_uSv=float or None,   # robot's accumulated dose and its limit
  expected=int,                           # drums the run was sent to check
  aisle_length_m=float or None,           # so unreached sections still appear
  aisle_start_x=float or None,            # where section 0 m starts (robot start); default 1 m before first stack
  lateral_pose=True,                      # False if telemetry only has distance along the aisle
  planted={drum_id: 'rust'},              # faults planted on purpose (test notes); {} if none
  groups=[dict(group='yellow', scope='all drums', drums=24, correct=23, accuracy=0.958, ci=[0.8, 0.99],
               found=6, faulty=7, false=0, missed=1)],   # per-colour accuracy; [] if none
  video=dict(summary=str, moments=[['0:00–0:13', 'what it shows']]) or None,
  truth={drum_id: dict(faulty=bool, rust=float or None, bulge=float or None)} or None,   # self-check only
  tech=[('Label', 'value'), ...],         # Technical details appendix: model names, SHAs, seed, commit
  drums=[dict(
    drum_id='A-L-01-T2',                  # <aisle>-<L|R>-<stack>-T<tier>; other IDs work but lose the plain "where"
    x=float, y=float,                     # metres, store frame
    category='LLW'|'ILW'|None,
    status='OK'|'Suspect'|'Confirmed defect'|"Couldn't inspect",
    reason=str or None,                   # required for "Couldn't inspect": why
    finding='none'|'corrosion'|'bulge'|'corrosion+bulge',
    confidence=float 0-1 or None,         # best confidence for the reported finding
    views=int, fault_views=int,
    view_list=[dict(image='/abs/path.png' or None, cls='rust'|'normal'|..., conf=float,
                    box=[x1, y1, x2, y2] in image pixels or None, size=(w, h) or None,
                    t=float seconds, label='pass 1 · view 2', frame=int, pitch=float deg, sha='<input sha256>')],
    dose_rate_at_drum_uSv_h=float or None, heat_rise_c=float or None,
    swab=dict(alpha=..., beta_gamma=...) or None,
    air_c=float or None, rh=float or None,
    h2=dict(ppm=float or None, status='below_detection' or None, limit=float or None) or None,
    label=dict(readable=bool, reads=['A-L-01-T2'], crop='/abs/path.png' or None) or None)],
  tele=[dict(t=float, x=float, y=float, gamma=float, h2=float, air_c=float, rh=float, dose_uSv=float)],
  events=[dict(t=float, drum=str or None, kind='plan'|'label'|'rating'|..., text=str,
               source='Cosmos planner'|'CANIS rules'|'Label reader'|..., latency_ms=int or None,
               action=str)],             # action: planner events only
)
```

Notes:
- Map your detector classes to findings in `CLASS_TO_FINDING` (loaders.py) and fault classes in `FAULT_CLASSES` (rules.py).
- Boxes must be in the pixel space of the image you point to, and `size` must be that image's size. Otherwise boxes land in the wrong place.
- `events` with a source containing "cosmos" are rendered as quoted planner reasons. Keep their text exactly as logged.

## 4. Wire it into the end of a run

Call the builder as the final step of the run script. A failed report must not fail the run:

```python
import subprocess, sys
r = subprocess.run([sys.executable, 'tools/full_hall_report/report/build_report.py', str(run_dir)])
if r.returncode:
    print('report step failed; the run still counts', file=sys.stderr)
```

On failure the builder still writes `index.html` and `summary.json` and leaves `report_error.txt`.

## 5. Check before you hand it over

- [ ] Spot-check 3 drums and 2 aisle sections in the PDF against the raw run files (status, confidence, gamma).
- [ ] Every flagged drum shows a photo with its box drawn on the drum. If a photo is missing, the report says "photo not logged".
- [ ] Sensors your run doesn't have print *not measured*, never 0.
- [ ] Planner text appears only in the step-by-step record, in quotes, matching the log exactly.
- [ ] `summary.json` counts match the checker or your run's own report.
- [ ] Render the PDF pages and look at them: no drum ID wrapping, no text overflow, no empty pages.
- [ ] No local home paths, tokens or Modal URLs anywhere in the PDF.

Reference outputs in `example/`: `CANIS_report_083203-wh_rigid_walk-de01.pdf` (36-drum showcase walk: 8 action needed, 28 no problem) and `CANIS_report_112205-adaptive_aisle-20f6.pdf` (adaptive-aisle take: 1 action needed, 1 check again, 4 no problem), each with its `summary` JSON. Page order and style: `docs/report_framework/README.md` sections 5–6.
