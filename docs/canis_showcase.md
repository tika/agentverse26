# CANIS 36-drum showcase

The system behind the final CANIS showcase video: a quadruped walks aisle A of warehouse-v3 in Isaac Sim, inspects 36 drums (24 yellow low-level, 12 blue intermediate-level) with the YOLO26s detector, and NVIDIA Cosmos Reason 2 chooses the next step from a fixed list of options.

## How a drum is decided

- The detector labels three views from the aisle. Damage in two or more views is a Confirmed defect.
- If the rules say OK, Cosmos can accept that or ask for a closer look.
- If the views are unclear, or the drum is on the top shelf, Cosmos can ask for a closer look or mark the drum as Suspect.
- A closer look adds five more views, and the fixed rules then decide. Cosmos can never clear a drum or confirm damage.

## Files

| File | Purpose |
|---|---|
| `scripts/hot/full_hall/wh_rigid_walk.py` | The walk: camera, motion, detector calls, Cosmos review, on-screen display |
| `scripts/hot/full_hall/wh_rigid_full_cosmos.py` | Settings for the full 36-drum walk |
| `scripts/hot/full_hall/wh_rigid_cosmos.py` | Settings for the six-drum clip |
| `scripts/hot/full_hall/cosmos_ping.py`, `yolo_ping.py` | Check that Cosmos and the exact detector are reachable before a render |
| `scripts/hot/full_hall/wh_score_color.py` | Scores a finished walk per drum colour against the seeded faults |
| `tools/full_hall_report/make_showcase.py` | Cuts the full video to under a minute, key moments in real time |
| `tools/full_hall_report/build_walk_report.py` | Builds the PDF inspection report from the run's logs |

## Running it

Needs the Modal secret `canis-conditions` and a private `.runtime/cosmos.env` holding `COSMOS_URL`, `VLLM_API_KEY` and `COSMOS_MODEL`. Never commit that file. The detector weights are checked by SHA-256 in `yolo_ping.py`.

```bash
export CANIS_DETECTOR_SECRET=canis-conditions HOT_GPU_COUNT=4
export HOT_FORCE_FAULTS='{"A-L-01-T1":{"corrosion_severity":0.85},"A-R-01-T1":{"bulging_severity":0.85}}'
H=tools/full_hall_report/hot_hall_canis.py; F=scripts/hot/full_hall
python $H cosmos-config .runtime/cosmos.env
HOT_SPAWN_X=1.24 python $H up
python $H run scripts/hot/prepare_robot_visuals.py
python $H run $F/env_fix.py $F/brand_data.py $F/wh_rigid_full_cosmos.py $F/wh_rigid_walk.py
python $H down
```

`down` only stops the function, so also stop the app with `modal app stop -y <app id>`. For the six-drum clip, use `wh_rigid_cosmos.py` in place of `wh_rigid_full_cosmos.py`. Set `HOT_SUFFIX=-short` to run a second worker alongside the first.

`HOT_FORCE_FAULTS` plants the two faults at the first column so the robot's response shows early. Leave it out to use only the seeded faults.

After the render, with `R` set to the run's `canis_wh_full_cosmos` folder:

```bash
python3 scripts/hot/full_hall/wh_score_color.py "$R" 42
python3 tools/full_hall_report/build_walk_report.py "$R" --commit "$(git rev-parse --short HEAD)"
```

`wh_score_color.py` needs the same `HOT_FORCE_FAULTS` as the run. `make_showcase.py` takes the full video, `telemetry.jsonl`, an output path and an ffmpeg binary. Its real-time segments are set for this run, so check them against `decisions.jsonl` for a new one.

## Result of the recorded run

| Drums | Correct | Accuracy | 95% range | Damaged drums found | False alarms |
|---|---|---|---|---|---|
| Yellow | 23 of 24 | 95.8% | 80–99% | 6 of 7 | 0 |
| Blue | 10 of 12 | 83.3% | 55–95% | 2 of 4 | 0 |

Scored against the simulation's seeded faults (seed 42) plus the two planted ones. Without the planted drums, yellow is 21 of 22 (95.5%). Detector: `compare_colors_20261108T053740Z_continued`, 168 calls, none failed. Cosmos made 29 reviews, all valid.
