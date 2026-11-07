# Agentverse26 — nuclear-store robot inspection

Build the Isaac Sim environment one step at a time, following **MVP v2**.
The environment now includes the fixed **28-drum hall**, seeded corrosion,
wet/dry releases, class + package labels, scalar sensors and Spot's body-mounted
RGB/depth camera. Repeated-seed rebuilds and actual Replicator box exports passed.

Start with [the complete environment handoff](docs/environment_handoff.md) for
local Isaac and Modal commands, editing, picture-ready settings and video capture.

- [Team quickstart and copy-paste agent prompt](docs/team_quickstart.md)
- [Run commands, installed APIs and validation](sim/README.md)
- [Environment build specification](docs/environment_mvp.md)
- [Sensors, inspection criteria, safety rules and limitations](docs/sensors_and_criteria.md)
- [Detector/camera API and training start gate](docs/training_handoff.md)

Use Python 3.12+ locally. Review each step through exported screenshots/video,
as selected by the user; this replaces the specification's interactive-viewer
instructions. Steps 1–4 and the requested training-label/camera handoff are
implemented; Step 5 shape faults and full-hall walking/agent integration remain.
The dog/planner prototypes below are retained as separate team workstreams.

```sh
python3 tools/run_environment.py       # build/edit the environment, no pictures
python3 tools/run_training_check.py    # RGB/depth, boxes and YOLO label proof
python3 tools/run_presentation.py      # final stills + MP4 flythrough
python3 -m unittest discover -s sim/tests -v
```

All new project work belongs in this repository. Rendered outputs are stored
locally under `sim/out/` and ignored by Git. No credentials belong in the repo.
The small procedural texture bank and `sim/hall.usda` are tracked so the hall
can be opened with its relative texture references after cloning.

## Spot prototype on Modal

Runs NVIDIA Isaac Sim 6.2.0 headless on a Modal L40S GPU, using the official `nvcr.io/nvidia/isaac-sim` image.

```sh
modal run isaac_sim_modal.py                              # smoke test -> out/smoke.png
modal run isaac_sim_modal.py --script path/to/sim.py      # run your own standalone script
modal run isaac_sim_modal.py --script sim.py --args "--steps 500"
modal shell isaac_sim_modal.py::shell                     # poke around inside the container
```

- Scripts run under Isaac Sim's bundled Python (`/isaac-sim/python.sh`) and start with `from isaacsim import SimulationApp`. See `scripts/smoke_test.py`.
- Files a script writes to `$OUTPUT_DIR` are copied back to `./out/`.
- Shader, kernel and extension caches persist in the `isaac-sim-cache` Modal Volume, to help reduce startup time. Each new Isaac process still initializes the renderer.
- GPU: Isaac Sim needs RT cores. Use L40S (the default), L4 or A10G, not A100 or H100. Switch with `ISAAC_GPU=L4 modal run isaac_sim_modal.py`.
- Running this accepts the NVIDIA Isaac Sim EULA (`ACCEPT_EULA=Y`).

## GUI in the browser (noVNC)

`isaac_novnc.py` runs the full Isaac Sim GUI on a virtual display (Xvfb → x11vnc → noVNC) behind a Modal HTTPS tunnel.

```sh
modal secret create isaac-vnc VNC_PASSWORD=<something>   # the tunnel URL is public
modal run isaac_novnc.py::check                          # needs NVIDIA graphics libs + Vulkan; stop if it fails
modal run isaac_novnc.py                                 # open the printed vnc.html link
```

- Code lives in `./sim`. Push with `modal volume put isaac-work ./sim /sim --force`, then type `sync` in the remote xterm to see the changes.
- `rec` in the xterm records the desktop to `/work/recordings` until Ctrl-C. Download with `modal volume get isaac-work /recordings .`.
- L40S, 8 CPUs, 32 GB RAM, 6-hour timeout. The GPU bills the whole time the desktop is up. Ctrl-C locally shuts it down.

## Spot inspection planner prototype

Run a synthetic patrol, spill detection and radiation stop:

```sh
python3 sim/spot_agent.py --demo
```

For recorded observations, pass a JSON limits file and a JSONL snapshots file.
Each configured sensor is required. This example uses synthetic values and units:

```json
{
  "radiation": {"unit": "sim_rad", "stop_at": 10, "max_age_s": 1},
  "thermal": {"unit": "sim_heat", "stop_at": 8, "max_age_s": 1}
}
```

One snapshot per line, with an image path relative to the working directory:

```json
{"rgb_path":"frame.jpg","readings":{"radiation":{"value":2,"unit":"sim_rad","age_s":0.1},"thermal":{"value":3,"unit":"sim_heat","age_s":0.1}},"findings":[{"id":"spill_1","label":"possible spill"}],"goals":[{"id":"view_drum_from_aisle","route_clear":true,"finding_id":"spill_1"}]}
```

```sh
python3 sim/spot_agent.py --limits limits.json --observations snapshots.jsonl
python3 sim/spot_agent.py --limits limits.json --observations snapshots.jsonl \
  --model /path/to/local/cosmos-reason2-2b
```

The first command uses the rules-based baseline. The second uses a staged Cosmos
Reason 2 checkpoint on CUDA with PyTorch, Transformers 4.57.3, Accelerate and
Pillow. Add `--adapter /path/to/adapter` with PEFT installed to compare a LoRA
checkpoint. The planner loads model artifacts from disk and emits JSON decisions
on stdout. This replay has no Isaac motion side effects.

In the live integration, the simulator should calculate sample ages from its
sensor timestamps and build candidate goals from the current map and depth
clearance. Run the safety check independently of model inference and recheck
the selected route and fresh readings before issuing motion. The limits schema
currently supports per-sensor upper limits. Rules involving accumulated
exposure, trends, or dwell time require separate logic.

## Headless Spot sensor collection

```sh
modal run isaac_sim_modal.py --script scripts/spot_rollout.py
modal run isaac_sim_modal.py --script scripts/spot_rollout.py --args "--seconds 5 --speed 1.2 --hz 4 --seed 8"
```

Each run saves a separate directory under `out/spot/` containing:

- `samples.jsonl` with a simulation timestamp, pose, sensor readings and their units, and the commanded velocity.
- `rgb/` and `depth/` with the corresponding forward camera PNG and NumPy optical-axis depth in metres. File paths in the manifest are relative to its directory. Non-finite depth denotes missing range.
- `scene_truth.json` with the seed, drum conditions and source strengths, and camera calibration. Keep drum truth separate from model inputs.

The collector uses the bundled Spot walking policy with a scripted forward command. Radiation is a noisy inverse-square sum, and thermal is a noisy distance-based scalar proxy. Both use simulation units. The rollout verifies upright displacement and saves a sample only when both camera channels are available and the camera timestamp has caught up to the sampled physics step.

For Cosmos QLoRA, turn selected samples into examples with an RGB frame, recent numeric sensor history, depth-derived clearance, findings, and available goals as inputs. Add a reviewed target goal or hold and a short evidence-based reason. Keep locomotion commands for debugging and add decision labels independently. Include clean drums, ambiguous visual findings, clear leaks, blocked routes, rising readings, and cases with no safe goal. Split by scene layout and seed so nearby frames from the same rollout stay together. YOLO needs image-aligned object boxes or masks as a separate labeling step.

## Spot development workflow

Headless Isaac on Modal is the verified path. The noVNC endpoint has served the
desktop, but Isaac reported uninitialized render backbuffers under Xvfb. Treat
`sim/spot_live.py` as an experimental Script Editor entry point until the
viewport is verified.

- **Planner and safety changes.** Replay recorded observations with
  `sim/spot_agent.py`. Use the rules baseline for fast iteration and load a
  local Cosmos checkpoint when comparing model behavior. Add candidate goals
  and findings to raw rollout samples before replaying them.
- **Scene and robot changes.** Use one shared scene definition for capture and
  previews. Keep the static hall and robot asset as USD references, and make
  drum state, spawn pose, and sensor settings editable scenario data. The current
  scripts each build their own scene. The next integration should consolidate
  that setup and let one warm headless process apply scenario changes between
  episodes. Use an explicit apply-and-reset command on Modal.
- **Capture.** Record the camera streams and sensor manifest headlessly.
  Use the camera render products for previews and measure cold startup,
  warm reset, physics, and rendering separately. Test
  `disable_viewport_updates=True` with the sensor cameras before adopting it.
- **Outputs.** Use unique run directories and write results to a Modal Volume
  before closing Kit so a disconnected client can retrieve them. The current
  headless runner returns its archive after the simulator exits.

For interactive editing on a working Isaac desktop, use **Window → Script
Editor** and load `/work/sim/spot_live.py` into an empty stage. Run it once,
then **Play**, **Stop**, edit, and **Play** again. On Modal, publish edits with
`modal volume put isaac-work sim/spot_live.py /sim/spot_live.py --force`
and run `sync` in the remote xterm before reading the file. Before replacing
the stage, stop playback and run `live_spot.close()` in the Script Editor.

See [Isaac development methods](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/introduction/workflows.html),
[Isaac performance guidance](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/reference_material/sim_performance_optimization_handbook.html),
and [Modal Volume reload semantics](https://modal.com/docs/guide/volumes).

### Warm walking-video worker

```sh
modal run --detach isaac_sim_modal.py::warm
```

The worker loads Spot and a fixed side camera, records one five-second pass,
then waits with the scene and renderer loaded. Find the worker's container with
`modal container list`. Request another take with
`modal container exec --pty CONTAINER_ID -- touch /tmp/spot-record`.
The path is a straight aisle at a 1 m/s forward command. This is a walking preview.

Each take has a unique directory on the `isaac-spot-takes` Volume. After the
`complete` marker appears, download the frames and assemble the video:

```sh
modal volume ls isaac-spot-takes /
modal volume get isaac-spot-takes /take-ID out/take-ID
ffmpeg -framerate 24 -i out/take-ID/%05d.png -pix_fmt yuv420p -movflags +faststart out/spot-walk.mp4
```

Stop the worker with `modal app stop APP_ID` when finished. The GPU stays
allocated between takes and Modal caps the worker invocation at 24 hours.

### Spill perception and detour

```sh
modal run --detach isaac_sim_modal.py --script scripts/spot_spill.py
ffmpeg -framerate 8 -i out/spot-spill/spill/%05d.jpg -pix_fmt yuv420p -movflags +faststart out/spot-spill.mp4
```

The dry and spill cases share the hall, Spot, and camera setup in one Isaac
process. The spill appears mid-run. A pixel detector looks for a fluorescent
magenta tracer and projects its mask centroid onto the floor. The rules baseline
blocks the direct aisle and selects the north cross-aisle when the estimated
spill is in the direct aisle. The detector receives RGB and camera geometry.
Depth is displayed separately. The scene's actual spill position is used to
score sampled base clearance.

Each case exports annotated frames, `events.jsonl`, and `score.json`.
The tracer and fixed alternate route make this a controlled perception test.
The demo uses a rules planner and a scripted scene event.

### Benchmark and Cosmos decision training

Use a separate output directory for each profile so the runs remain comparable.

```sh
modal run isaac_sim_modal.py --script scripts/spot_spill.py --output out/bench-default
modal run isaac_sim_modal.py --script scripts/spot_spill.py --args=--fast --output out/bench-fast
```

See [the timing baseline and detector handoff](docs/spot_development.md).
Validate exported decision captures locally before starting a GPU job:

```sh
python3 tools/train_spot_lora.py out/bench-default/spot-spill
modal run tools/train_spot_lora.py --data out/bench-default/spot-spill --steps 1
```

The one-step GPU check needs approved access to Cosmos Reason 2 and an HF_TOKEN
in the Modal secret named `huggingface`. The adapter and timing report are
written to the `spot-cosmos-training` Volume. Use separate layouts and decision
labels for an evaluation run.

### Spot radiation walk

```sh
modal run isaac_sim_modal.py --script scripts/spot_spill.py --args=--radiation --output out/radiation-demo
ffmpeg -framerate 8 -i out/radiation-demo/spot-radiation/radiation/%05d.jpg \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart out/spot-radiation.mp4
```

This mode uses the full hall inventory. Each drum has simulator-side USD
attributes for source strength at one metre and source height. The scenario
raises one source to make the transition visible during a short walk. The
body-mounted gamma detector samples the existing dose and environment
backend. The controller uses measured dose only to veto the forward path
and back off toward a previously sampled location. The overlay shows the
dose-rate history and configured thresholds in simulation units, with air
temperature and humidity alongside. The event log records dose, position,
accumulated exposure and the veto. This is a simulated gamma survey, and
the overlay reports dose at the sampled position.
