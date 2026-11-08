# Reproduce the approved rigid-camera recordings

These are short **stationary camera/model tests** in warehouse-v3, seed 42.
They use the latest expanded YOLO26s and the approved CANIS layout: original
header, robot corner view, minimap, counters and decision log. The whole native
camera image is fitted below its caption; no edge is covered by the HUD.
The demos do not run Cosmos or implement the full aisle inspection mission.

## Set up the worker

Start from updated `main`. Configure a private detector secret as described in
[the latest-model handoff](../detector/v2/LATEST_MODEL.md). Callers must select
the expanded endpoint with checkpoint SHA
`ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a`.
The scripts reject an unexpected checkpoint or an image-hash mismatch.

```sh
CANIS_DETECTOR_SECRET=drum-detector-expanded HOT_GPU_COUNT=1 \
  HOT_WAREHOUSE_SEED=42 \
  python3 tools/full_hall_report/hot_hall_canis.py up
```

Reuse your owned worker for subsequent requests. Its namespace must contain
the warehouse map and body-mounted front camera supplied by `sim/hot_server.py`.
Do not start a second worker on the same shared request queue. Four GPUs can be
requested with `HOT_GPU_COUNT=4`, but a controlled four-versus-one speedup has
not been established.

## Middle drum, then upper drum

```sh
HOT_NO_OPEN=1 python3 tools/full_hall_report/hot_hall_canis.py run \
  scripts/hot/prepare_robot_visuals.py \
  scripts/hot/full_hall/brand_data.py \
  scripts/hot/full_hall/rigid_posture.py \
  scripts/hot/full_hall/rigid_recording_setup.py \
  scripts/hot/full_hall/rigid_middle_upper.py
```

The job selects front-facing `D30 / A-L-01-T2` and `D32 / A-L-01-T3` by map
geometry. It captures the middle drum at neutral pitch, then views the upper
drum at 5 and 10 degrees of requested physical body pitch. A partial camera
view triggers a higher look; a clear model result is shown only after the
target's projected bounding box fits inside the detector input. These simple
visual rules are not the agent's full distinct-view or thermal inspection
criteria.

The recorded test produced a **14.25-second, 1920×1080, 24 fps** MP4. The
model returned normal for the middle drum at 96.8% confidence and the upper
drum at 95.2%. These are individual predictions, not accuracy estimates.

## One upper drum

Use the same command with the final file replaced by:

```text
scripts/hot/full_hall/rigid_one_drum.py
```

This records `A-L-01-T3` with physical pitch requests of 0, 5 and 10 degrees.
It retains the same display layout, camera mount, model and output contract.

## Camera, movement and outputs

- Camera: `/World/WalkingSpot/body/FrontCamera`, native 1280×720, horizontal
  FOV 110 degrees, fixed body-relative position `[0.60, 0, 0.12]` metres.
- Fixed mount: 15 degrees upward; world-camera-convention quaternion
  `[0.9914448614, 0, -0.1305261922, 0]`. The mount is configured before filming
  and its local pose is checked throughout. It never tracks a drum on its own.
- Movement: a known standing pose is initialized before filming. Leg IK and
  joint torques produce the recorded body pitch. The robot presentation view
  supplies no model input. The worker's default pose/calibration are restored
  after the clip.
- Detector: a declared 720×720 center crop of the native front image is
  resized to 640×640 for upload. Responses map back onto the native frame.
  The display fits the entire native image inside `[0,100,1280,780]` on the
  1920×1080 output, using letterboxing rather than cropping.
- Box/result holds use the exact detector input frame. Physics/model requests
  are synchronous; video playback speed is not wall-clock inference speed.

The supervisor downloads the MP4 and report into `out/canis_wh/REQUEST_ID/` and
persists the bundle in `canis-wh-runs:/runs/REQUEST_ID/`. Within each recording
folder, `tilt_report.json` contains the target IDs, fixed mount, measured body
pitch, framing, predictions, model hashes, decisions and status. `inputs/`
contains unannotated native images, uploaded crops and API responses. Verify
each response's `input_sha256` against the corresponding `*_model.png` file.

The original two-drum evidence is also retained in the separate test volume:

```sh
python3 -m modal volume get canis-expanded-video-runs \
  /runs/072814-middle_upper_original_layout-58ee ./out/approved-two-drum
```

Only stop a worker you own. The existing main aisle script still uses its
independently aimed `CanisEye`; it has not been converted to this rigid mount.
Extending these clips to the aisle requires integrating physical standing /
walking transitions and the camera/HUD adapter into that loop. This handoff
does not claim that the full aisle or Cosmos integration is complete.
