# Full-hall environment and detector handoff

Use `docs/team_quickstart.md` for Modal account/workspace setup. This workflow
builds the original 28-drum hall, not the separate walking tracer fixture.
It preserves the team's existing walking, planner, benchmark and LoRA scripts.

## Build and capture on Modal

From a clone of the merged main branch, with Python 3.12+:

```sh
python3 -m pip install -r tools/requirements.txt
modal setup
python3 -m unittest discover -s sim/tests -v
python3 tools/run_training_check.py
python3 tools/run_robot_check.py
```

Existing authenticated users do not need to repeat `modal setup`.
Each command starts a short-lived RTX-capable GPU function, uploads the current
`sim/` source and texture bank, downloads results into this checkout, then stops.
No desktop, browser, noVNC tunnel or persistent video worker is required.
The robot check needs access to NVIDIA's built-in Spot asset library.

A running warm walking-video worker cannot load these scene edits; use the
commands above. Do not stop someone else's worker. Inspect `modal container list`
and match the app ID printed by your own job.

## Run in another Isaac Sim installation

The verified image is Isaac Sim 6.2.0, reporting
`6.2.0-rc.14+release.52805.02189a84.gl`. From the repo root on Linux with an
RTX-capable NVIDIA GPU, use that installation's actual `python.sh` path:

```sh
/path/to/isaac-sim/python.sh sim/test_render.py --allow-root
/path/to/isaac-sim/python.sh sim/capture_robot.py --allow-root
```

Omit `--allow-root` when not running as root. All hall, drum and defect textures
are procedural and checked in under `sim/assets/generated/`; USD references
are relative to the scene file. Keep the `sim/` directory intact when copying.
Open `sim/scene_training.usda` for the hall/faults/labels or
`sim/scene_robot.usda` for the hall with bundled Spot and onboard camera.
The robot USD references NVIDIA's asset library; it is not vendored here.
The scene files are snapshots. The Python builders are the source of truth.

Do not run these scripts with ordinary system Python: they need Isaac's bundled
runtime. Local geometry, sensor and exporter tests run with ordinary Python plus
NumPy and Pillow (already included in Isaac; install them locally for tests).

## API inside an already-running Isaac script

Put the repository's `sim/` directory on `sys.path`, then:

```python
from layouts import load_layout
from drums import set_drum_faults, set_drum_state

load_layout()                         # checked-in layout, seed 42
load_layout(seed=43)                  # new reproducible appearance/fault episode
set_drum_faults('D10', ['corrosion', 'leak'], seed=36, severity=3)
set_drum_state('D10', 'rusted', seed=36, severity=3)  # compatibility alias
set_drum_state('D10', 'clean')         # remove all its fault meshes
```

Calls replace a drum's previous defects, update `drums.json` and restore labels.
The supported Step 3/4 fault names are `corrosion`, `leak`, `residue`.
`set_drum_state` also accepts `rust`, `rusted`, `spill`, `ok`, composable strings
such as `corrosion+leak`, or a fault list. Unknown/later fault names raise an
error rather than silently producing a clean object.

`sim/layouts/layout_training.json` lists faulted packages. Unlisted packages
are clean. Coordinates, IDs, yaw, sizes and source strength retain the original
inventory. Calling `load_layout` twice with the same seed is checked for
identical stage text and inventory, and fault replacement is checked explicitly.
A different episode seed changes seeded appearance/defects, not the fixed layout.
A seed is not itself a physically independent layout for evaluating generalisation.

## Classes and outputs

Canonical detector class IDs are fixed:

```text
0 drum
1 corrosion
2 spill
```

The drum root carries `class=drum`, `drum_id=Dxx`, inherited by its body, lid and
hardware. This produces one complete drum box. Each corrosion/release mesh under
`/World/Defects/Dxx/` has its own class and drum-ID label. There are no classes
on walls, floor, markings, signs, clean weld tint, robot or background details.
The entire drum's ID plate is included in the drum's inherited class; it is not
a separate detector category or independent target.

Replicator's tight boxes come from actual rendered geometry. Fault silhouettes
are irregular, curved meshes 3 mm above the drum profile, following chimes and
rolling hoops. They are not large transparent rectangular quads. Replicator
normalises semantic values to lowercase; exported JSON converts identities back
to canonical `Dxx` spelling. Class order does not depend on semantic numeric IDs.

`sim/out/test_render/<case>/` contains:

- `rgb_0000.png`: raw training RGB, with no overlays.
- `distance_to_image_plane_0000.npy`: float optical-axis depth, metres.
- `bounding_box_2d_tight_0000.npy` and labels JSON: native Replicator output.
- `boxes.png`: review overlay drawn from those native boxes.
- `boxes.json`: readable class, drum ID and pixel XYXY list.
- `labels.txt`: matching YOLO detection labels, normalised centre/width/height.

The check renders corrosion at three LLW and two ILW severities, wet/dry releases
in both categories, a hall overview and two mixed-fault proofs. The required
training start gate is `sim/out/test_render/report.json` with
`training_start_signal=true`. This is written only after non-black RGB and real
boxes for all three classes pass for D10 (corrosion + leak) and D25 (corrosion +
residue). A file existing or a zero simulator exit code alone is not a pass.

These are proof frames, not a statistically adequate training set. The detector
teammate still owns bulk capture/randomisation, independent train/validation/test
splits, training and TensorRT export. Avoid splitting adjacent views of the same
seeded scene across train and evaluation. Boxes alone do not establish rust
surface percentage: use a mask or another area estimator for that criterion.

## Dog cameras and capture_frame

```python
from robot import load_robot, attach_cameras, capture_frame

spot = load_robot(position=(4.5, 5.5, 0.55), yaw=1.57079632679)
attach_cameras(spot['body'])
result = capture_frame('sim/out/my_frames', app=simulation_app,
                       frame_index=0, sim_time_s=0.0)
```

The inspection camera is a true child of Spot's body link, so it inherits body
motion. RGB and depth share one 640×640 render product and calibration. It is
mounted at an initial 0.6 m world height, looking along local +X with 10° downward
pitch and approximately 77° horizontal FOV. Intrinsics and the full world camera
transform are recorded, not guessed from a screenshot.

`capture_frame` writes `rgb_0000.png`, float32 `depth_0000.npy` and
`meta_0000.json` at the requested output root, plus native annotations, review
boxes and YOLO labels under `frame_0000/`. Metadata includes base XY/yaw, camera
pose, calibration, units and the simulation time supplied by the caller.

This check loads Spot in a static pose. It does not add another navigation/gait
controller or claim the full-hall agent works. The team's existing walking
scripts remain separate and unchanged by the camera integration. Body-mounted
sensor data can be wired into that controller in the next integration step.

## Rendering and limits

RTX Minimal was verified in installed launch-source APIs and tried for this
scene, but generated black RGB despite semantic boxes. The handoff uses the
previously verified real-time `RayTracedLighting` renderer. No high-sample path
tracer is used. Isaac's supported camera/Replicator pipeline still requires RTX;
turning ray tracing entirely off does not yield usable sensor images here.
See NVIDIA's [render modes](https://docs.isaacsim.omniverse.nvidia.com/latest/reference_material/rendering_modes.html).

Rust stages are procedural approximations, not scanned/validated corrosion.
The small bank includes mottled oxide layers, blisters, pitting, scale,
stainless tea stain/weep/crevice features and dry/active release textures.
Stage-4 dark perforation spots are visual approximations, not through-holes or
wall-strength physics. Corrosion severity controls visual mix, not remaining
wall thickness. Puddles are static shallow meshes; roughness and normal maps
approximate wet film, crust and evaporation rings. They are not simulated fluids.
Do not label clean weld heat tint or ordinary grime as corrosion.

Step 5 bulges/dents/obstructions, hidden internal corrosion, the full four-case
Step 6 obstruction/bulge proof and robot walking integration remain beyond this
Step 1–4 training handoff. Nothing here claims those later checks passed.
