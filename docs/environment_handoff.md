# Environment handoff — reproduce, edit and make picture-ready

This is the full **28-drum environment**, with the original hall and exact drum
positions preserved. It combines the environment work with the team's Spot,
perception, benchmark and LoRA work; those separate prototypes are retained.

## What is ready

- Procedural 20×12×6 m hall, lighting, signs, aisle markings and navigation graph.
- 16 painted 200 L LLW drums and 12 stainless 500 L ILW drums; readable stable IDs.
- Seeded external corrosion, wet releases, dry residue and deposits, represented
  by separate conforming/lobed meshes rather than painted-on detector labels.
- `drums.json` records every package and defect; nominal dimensions stay nominal.
- Exactly three detector classes: `drum`, `corrosion`, `spill`, plus `drum_id`.
- Rebuildable layout, replaceable fault states, metric depth and actual Replicator
  tight-box export with YOLO labels. The mixed LLW/ILW test pictures pass.
- Bundled Spot asset with body-mounted RGB/depth camera and `capture_frame()`.
  Spot is parked in this environment check. Walking/agent integration remains
  separate from the team's existing walking prototypes.
- Configurable scalar sensors and inspection/safety criteria from the earlier
  sensor extension. These are not calibrated nuclear safety instruments.

The environment-only Modal run reported **28 drums, 9 faulted drums, 31 defect
meshes** and a 2.6 s hall/layout build after Kit startup. The repeated-seed test
compared identical USD and inventory and verified that clearing a state removes
its old meshes. GPU/Kit startup and image rendering take additional time.

## 1. Get the complete code without losing your changes

```sh
git clone https://github.com/tika/agentverse26.git
cd agentverse26
```

For an existing checkout, checkpoint your work before combining main:

```sh
git status
git add <your-intended-files>
git commit -m "Checkpoint environment edits"
git fetch origin
git merge origin/main
```

Resolve any conflicts by preserving both workstreams. Do not use reset/clean or
force-push to synchronise. Start a workstream branch for further edits. Record
`git rev-parse HEAD` with captured outputs; a seed reproduces a scene for the
same source and texture-bank revision, not arbitrary future code revisions.

## 2. Choose Modal or your own Isaac installation

**Modal, from Mac/Linux/Windows with Python 3.12+:**

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
modal setup
python -m unittest discover -s sim/tests -v
python tools/run_environment.py
```

Use the team's agreed Modal workspace. Skip `modal setup` if already logged in.
The job uploads your current local source, builds without taking pictures,
downloads `sim/scene_environment.usda`, textures, inventory and report, and stops
its GPU. It does not launch a GUI or keep a billable preview worker running.
The unrelated warm Spot-video worker only replays its own fixed scene.

**Your own Linux Isaac Sim 6.2.0 installation:**

```sh
/path/to/isaac-sim/python.sh sim/build_environment.py --allow-root
```

Remove `--allow-root` for a non-root process. Use Isaac's Python, not system
Python. The verified NVIDIA container is `nvcr.io/nvidia/isaac-sim:6.2.0`, reporting
`6.2.0-rc.14+release.52805.02189a84.gl`. Use an RTX-capable NVIDIA GPU with enough
VRAM; Modal L40S and A10-class hardware built this environment. A100/H100 do not
provide the required RTX render path.

Open **`sim/scene_environment.usda`** in Isaac Sim for the editable scene. Keep
`sim/assets/` next to it. Hall/fault textures are included and use relative paths.
Spot references NVIDIA's built-in asset library and requires asset access/cache.
The authored root is `/World`; units are metres and Z is up. The environment
builder parks Spot at (1,6,0.55), facing +X. It does not start a walking policy.

## 3. Reproduce or modify the scene

```sh
/path/to/isaac-sim/python.sh sim/build_environment.py --seed 42 --allow-root
/path/to/isaac-sim/python.sh sim/build_environment.py --seed 43 --no-robot --allow-root
```

The default layout is `sim/layouts/layout_training.json`. Pass `--layout` for a
copy you created. Output defaults to `sim/scene_environment.usda`; `--output`
may select another filename **inside sim/**. Copy the complete `sim/` directory
when sharing scenes. Build and capture scripts may update `drums.json`; it
always describes the most recently built episode, not every historical snapshot.

The exact coordinate inventory is defined in `sim/drums.py`; the fault layout
selects packages, faults, severities and local seeds. `load_layout(seed=42)`
rebuilds the hall/drums, removes old defects and applies the checked layout.
Change the episode seed to change appearance/fault samples while retaining the
28 fixed positions. Do not silently change category or size when editing labels.

Inside an Isaac script with `sim/` on `sys.path`:

```python
from layouts import load_layout
from drums import set_drum_state, set_drum_faults

load_layout(seed=42)
set_drum_faults('D10', ['corrosion', 'leak'], seed=36, severity=3)
set_drum_state('D10', 'clean')
```

`set_drum_state` also accepts `rust`, `rusted`, `spill`, `ok` and composable fault
strings. Unsupported later fault types fail explicitly. `set_drum_category`
changes geometry/material/ID plate/source strength and resets that package's
faults to clean; reapply desired faults afterwards.

| What to edit | File |
| --- | --- |
| Hall geometry/lights | `sim/build_hall.py` |
| Drum dimensions and appearance | `sim/profiles.py`, `sim/drum_textures.py`, `sim/drums.py` |
| Which packages have faults | `sim/layouts/layout_training.json` |
| Fault geometry/material patterns | `sim/defects.py`, `sim/defect_geometry.py`, `sim/fault_textures.py` |
| Semantic classes and package IDs | `sim/labels.py` |
| Sensors and inspection thresholds | `sim/sensors.py`, `sim/criteria.py`, `sim/inspection_config.json` |
| Body-mounted camera and output metadata | `sim/robot.py` |
| Final screenshots/video | `sim/capture_presentation.py` |

All random generators derive from explicit seeds. Texture bank files are cached;
if editing procedural texture code, bump the bank version suffix or remove only
the relevant generated cache files. Otherwise the previous textures will be reused.

## 4. Make it picture-ready

```sh
python tools/run_presentation.py
```

This builds the same seeded environment, parks Spot near D10 for a presentation
view, and renders six stills plus an eight-second camera flythrough. The scene
stays stationary; only the review camera moves. This is an environment tour,
not footage of autonomous locomotion. It saves camera poses and exposure in
`sim/out/presentation/manifest.json`, downloads the real PNG frames, then uses
the FFmpeg binary supplied by `imageio-ffmpeg` to produce an H.264 MP4 locally.

On a local Isaac machine:

```sh
/path/to/isaac-sim/python.sh sim/capture_presentation.py --allow-root
```

Encode `sim/out/presentation/video_frames/%05d.png` at 10 fps with FFmpeg, using
H.264, `yuv420p` and `+faststart`; the Modal wrapper demonstrates the exact call.
All stills are 960×640. Files are named `hall_overview.png`, `robot_in_hall.png`,
`llw_corrosion.png`, `ilw_corrosion.png`, `llw_leak.png`, `ilw_residue.png` and
`environment_walkthrough.mp4`.

Picture settings are explicit:

- Use the verified real-time renderer. RTX Minimal was tested but produced black
  RGB here. This camera pipeline has no supported non-RTX replacement. The Kit
  compatibility layer may report `RealTimePathTracing` internally despite the
  requested `RayTracedLighting` launch setting; this is the real-time pipeline,
  not an offline high-sample render.
- Disable automatic exposure; use ISO 400, f/2.8, 1/60 s. Apply after asset and
  camera creation. A manually opened USD uses the viewer's exposure settings;
  USD alone does not carry all Kit render settings.
- Hall lights are already authored: seven 4500-intensity fixtures, one at 1800,
  plus dim dome fill. Review lights before increasing exposure so steel and
  wet surfaces retain contrast.
- Use the scene's actual materials and texture bank. Keep RGB separate from
  box overlays. Do not use fake visual annotations as training pixels.
- Keep the camera out of drums/walls, avoid extremely wide closeup lenses, and
  retain visible floor around leaks. Use one review camera and hide viewport
  guides for clean pictures. Let materials load before recording.

The stills are scene renders. No generative images or synthetic post-painted
faults are used. Some material effects are procedural approximations; this is
not a corrosion-science validation or physical fluid simulation.

## 5. Detector handoff and training GPU

```sh
python tools/run_training_check.py
python tools/run_robot_check.py
```

The training check saves raw RGB, native tight boxes, review overlays and
normalised YOLO labels for the exact classes `drum=0`, `corrosion=1`, `spill=2`.
It passes only when both mixed-fault test cases contain all three target classes
and non-black RGB. Its machine-readable gate is:
`sim/out/test_render/report.json` → `training_start_signal: true`.

The robot check saves `rgb_0000.png`, float32 metric `depth_0000.npy` and
`meta_0000.json`, including camera calibration, world pose and simulation time.
The camera is a child of `/World/Spot/Robot/body`, initially at 0.6 m world height,
pitched 10° down, 640×640. See [the detailed training handoff](training_handoff.md)
for the API and label contract. Bulk dataset creation/training is still the
perception teammate's work; these checks are the start signal, not a trained model.

Every environment/capture job closes Isaac and terminates its own GPU container.
Before a roughly 40-minute training slot, finish all capture jobs and check
`modal container list`; stop only workers you own. There is no automatic GPU
reservation: coordinate the slot in your team's workspace. Do not leave the
24-hour warm walking-video worker using the GPU intended for training.

## Limits and later integration

Visible Step 3/4 defects and labels are ready for dataset work. Bulges, dents,
obstructions, hidden internal-corrosion truth and the full later-case test suite
are not implemented in this builder. The full-hall agent is not yet connected
to the walking controller. Existing team prototypes remain available.
Rust and contamination appearances are procedural; measured inspection severity,
remaining wall strength and real nuclear safety cannot be inferred from the
visual severity integer or these simulation thresholds.

## Checked-in review results

The mixed-fault training gate passed (`training_start_signal: true`), the
body-mounted camera produced RGB/depth/calibration metadata, and the final
walkthrough decoded as 80 H.264 frames at 10 fps, 960×640 (8 seconds). All eight
local behaviour/regression checks passed. Isaac and the owned Modal GPU jobs
were stopped after capture.

[Preview images and video](previews/README.md) are committed for teammates who
have not run the captures yet. [Environment build](validation/environment_build.json),
[training/box check](validation/training_check.json),
[robot camera check](validation/robot_camera_check.json) and
[presentation camera manifest](validation/presentation_manifest.json) record the
actual results. The source scripts can regenerate them; massive raw frame
folders and logs are intentionally kept outside Git under `sim/out/`.
