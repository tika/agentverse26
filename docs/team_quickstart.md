# Team quickstart

Work from the same Git revision and use a separate branch for each workstream.
The verified workflows run headlessly on Modal and return screenshots, video
frames, or sensor logs. Isaac Sim runs in the container, so teammates only
need Python 3.12+, Git, and access to a Modal workspace with RTX GPUs.

## First run from a fresh clone

```sh
git clone https://github.com/tika/agentverse26.git
cd agentverse26
git switch main
git pull --ff-only
git rev-parse --short HEAD

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
modal setup
python -m unittest discover -s sim/tests -v
```

During Modal setup, select the workspace your team agreed to use. App IDs,
containers and Volumes belong to that workspace. Use the app URL or app ID to
identify a run. Several apps can all be named `isaac-sim`. If you already cloned
the repo, start with the branch and pull commands.

## Warm Spot video worker

Start one fresh worker for your session. On a shared workspace, coordinate who
owns it so teammates can reuse the same preview worker instead of each keeping
an L40S allocated.

```sh
modal run --detach isaac_sim_modal.py::warm
```

Save the app ID printed by the command. Wait for `Warm and waiting` in its
logs. Isaac loads once, records a five-second walk, then waits with the scene
loaded. To request another take, find the container that belongs to that app.

```sh
modal container list
modal container exec --pty CONTAINER_ID -- touch /tmp/spot-record
modal volume ls isaac-spot-takes /
modal volume ls isaac-spot-takes /take-ID
```

Use the take ID printed by the worker. After the `complete` marker appears,
download into a directory that already exists. Install FFmpeg locally for the
last command.

```sh
mkdir -p out/team-takes
modal volume get isaac-spot-takes /take-ID out/team-takes
ffmpeg -framerate 24 -i out/team-takes/take-ID/%05d.png \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart out/take-ID.mp4
```

The warm worker replays the **fixed Spot video scene**. A fresh launch picks up
the code from the checkout that starts it. A running worker does not pick up
Git pulls, new Python, or asset changes, and it cannot run the drum or dataset
entry points. Use the role-specific commands below for changes. There is
currently no shared warm worker for arbitrary scene edits. The noVNC path has
failed to initialize the viewport under Xvfb.

The worker keeps its GPU between takes and has a 24-hour Modal timeout. Only
the owner should stop it, using `modal app stop APP_ID`.

## Pick your workstream

| Workstream | Start here | First review artifact |
| --- | --- | --- |
| Barrel appearance | Edit `sim/drum_textures.py`, `sim/profiles.py`, and `sim/drums.py`. Run `python tools/run_drums.py`. Keep stable drum IDs and nominal dimensions unless intentionally changing the design. | Drum closeups in `sim/out/step2/`. Review lighting, texture and silhouettes before a larger render. |
| YOLO and TensorRT | Run `python tools/run_sensors.py` for a verified RGB/depth example. Use `sim/build_hall.py` and `sim/capture_sensors.py` as entry points for eye-level captures. Add visible faults and validate the USD labels and boxes with a small batch before bulk generation. | Raw RGB with label overlays and per-class counts. Keep layout-based train, validation and test splits, and hold the demo layout out. See the [detector handoff](spot_development.md#proposed-tensorrt-response-contract). |
| Perception, paths and scenarios | Start with `scripts/spot_spill.py` and use `sim/aisles.json` for the full hall waypoint graph. Run `modal run isaac_sim_modal.py --script scripts/spot_spill.py --output out/scenario-check`. Use `sim/spot_agent.py --demo` with Python for local planner replay. | Compare dry and spill `score.json`, event logs and annotated frames under `out/scenario-check/spot-spill/`. Preserve the known-good default renderer and record timings. |

The bulk YOLO dataset exporter and trained TensorRT engine are teammate
deliverables. Keep raw training RGB separate from masks, boxes and review
overlays. The current spill demo detects a synthetic magenta tracer with rules.

## Which sensors are ready?

| Need | Available today | Still to wire up |
| --- | --- | --- |
| Bulges | Aligned metric depth on the stationary rig and onboard depth in the Spot prototype. Criteria accept diameter change. | Visible bulge variants and a diameter estimate from segmented depth at multiple viewpoints. |
| Corrosion and rust | RGB and criteria for visible rust percentage and lifting-feature overlap. | Fault visuals and semantic labels, then detection. Rust area percentage needs a mask or another area estimator in addition to boxes. |
| Radiation | The full-hall Python sensor provides simulated dose rate and cumulative dose, with optional directional bins. | Connect these packets and safety responses to the moving Spot controller. |
| Perception | The walk demo has an RGB spill mask, depth readout, event log and working detour. | Replace or supplement the tracer with the TensorRT detections and wire the full criteria and safety loop. Cosmos/LoRA is scaffolded and awaits model access. |
| Depth of field / depth | Metric optical-axis depth and range on the stationary rig, and onboard depth in the prototype. | Depth of field means optical blur, which is separate from metric depth. Use raw depth arrays for distance and geometry. |

The full 28-drum sensor check uses a stationary camera. The walking spill
prototype references the same hall geometry with a smaller fixture and its own
onboard camera. Simulated swab, temperature and humidity are implemented in
the full-hall sensor backend. See [sensor details](sensors_and_criteria.md).

## Copy-paste prompt for a teammate's coding agent

```text
Work in tika/agentverse26. Read docs/team_quickstart.md and check my branch,
Git status, and Modal workspace before launching any GPU work.

My role is [barrel appearance / YOLO + TensorRT / perception + paths].
My first change is [one concrete change]. Start on a new branch from main.
Run the smallest role-specific check and show me the local artifact path,
app ID, elapsed times, and any paper cuts. Keep generated output out of Git.

Check for an existing team warm worker first. It can replay the fixed Spot
preview. For changed code or assets, run the appropriate entry point from my
checkout. Keep other people's Modal apps running. If a dedicated warm worker
is needed, report its app ID, owner, and how to stop it.
```
