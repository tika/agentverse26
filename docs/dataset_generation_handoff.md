# Dataset generation: single-workspace agent handoff

## Objective and current authorization

**The user has now authorized the full 1,200-image run on up to 10 RTX PRO 6000
workers in `paramsachdeva07`. Training is not authorized by this dataset task.**
The earlier one-image benchmark is complete; do not repeat it or launch duplicate
generation jobs. First check the active run and release as described below.
No second account or cross-account workflow is involved.

Full run launched 7 November 2026: **`20261107T213255Z_26d31d`**, Modal app
`ap-ur84IBTFBexuI9dXtq2eyX`. Check this run before launching another:
`python detector/status.py 20261107T213255Z_26d31d`.

Code branch: **`detector-training`** in `https://github.com/tika/agentverse26`.
This branch includes the latest merged main at the time of publication. Preserve
local work, never reset/clean/force-push and never stop another person's Modal
app or hot hall worker. Read this file before running older training prompts.

## Fresh setup

Run from the repository root with local Python 3.12 or newer:

```sh
git clone --branch detector-training https://github.com/tika/agentverse26.git
cd agentverse26
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt
modal setup
modal profile list --json
python -m unittest detector.test_pilot detector.test_release -v
python -m unittest discover -s sim/tests -v
```

For an existing checkout, inspect `git status` first and merge the remote branch
normally. Do not clone over an existing folder or discard changes. If Modal is
already authenticated, skip setup. Activate a profile whose **workspace** is
`paramsachdeva07`; profile names themselves can differ. Do not paste tokens into
the repository or chat. The runner and publisher reject the wrong workspace.

No local Isaac installation or local NVIDIA GPU is needed. Do not install Torch,
YOLO, TensorRT or unrelated packages into Isaac's bundled Python. The renderer
uses the official `nvcr.io/nvidia/isaac-sim:6.2.0` container, not GUI/noVNC.

## Check for an existing run before starting

```sh
modal app list
modal volume ls detector-data /releases/barrels_v2_1200
modal volume ls detector-data /pilots
```

If the release already exists, inspect its manifest and report it; do not start
another billable generation job. If the generator is already running, find its
run ID in the launch log or Volume and monitor it instead of launching a duplicate.
A missing release directory is expected before the first run. Do not stop other
apps to free GPUs. Actual concurrency depends on workspace limits/availability.

## Completed one-image timing check (historical reproduction command)

```sh
mkdir -p out/logs
python detector/modal_pilot.py \
  --seeds 1 --seed-start 1001 --frames-per-seed 1 --workers 1 \
  --gpu RTX-PRO-6000 --workspace paramsachdeva07 --benchmark-l40s \
  > out/logs/barrel_gpu_benchmark.log 2>&1
```

This saves one image per GPU (two total), compares cold job time and stops.
It has already been completed; the authorized current task uses the next command.
Do not add `--plan` or `--publish` to this check. The JSON speedup after the first
frame is null: one frame cannot measure steady-state throughput. Report the
observed startup/capture times and stop; do not automatically move on below.

The completed check on 7 November measured 106.16 s on RTX PRO 6000 and 166.15 s
on L40S (36.1% less time for the RTX job). See
[the recorded measurement](validation/gpu_one_image_benchmark.json). This includes
scene construction, warm-up, capture, export and worker overhead. It does not
measure sustained rendering throughput; a full dataset time is still an estimate.

## Authorized full generation command

The checked-in `detector/plans/barrels_1200_v1.json` is the authoritative plan.
It assigns 61 unique seeds starting at 1001, separate from the inspected pilot
seeds. The job sizes are 20 images, except two 10-image scenes needed to reach
the exact held-out split counts. Every scene stays in one split.

```sh
mkdir -p out/logs
python detector/modal_pilot.py \
  --plan detector/plans/barrels_1200_v1.json \
  --workers 10 \
  --gpu RTX-PRO-6000 \
  --workspace paramsachdeva07 \
  --publish barrels_v2_1200 \
  > out/logs/barrels_1200.log 2>&1
```

Keep the process running. Use another terminal for `tail -f out/logs/barrels_1200.log`.
The log prints `PILOT_RUN RUN_ID`, the output directory and Modal app URL. The
first production scene must pass before the remaining jobs are submitted.
The optional `--benchmark-l40s` flag runs a separate matching control scene and
reports `GPU_BENCHMARK`. It is omitted for this full run because the requested
one-image comparison has already completed. No control images enter the dataset.

Rendering is capped at 10 concurrent production workers, regardless of the 61
queued scenes. Each worker has a 20-minute timeout and an earlier subprocess
kill timer. The first compatibility test/control occupy at most two GPUs before
the production fan-out. Successful workers terminate; there is no idle GPU server.

## Progress and completion

```sh
python detector/status.py RUN_ID
```

This allocates no GPU. It reads durable per-scene progress from the Volume and
reports validated images, completed scenes and active workers. Expected stages
are `starting_isaac`, `building_assets`, `rendering`, `validating`, `complete` or
`failed`. A scene counts only after real RGB and annotations pass validation.
Logs include elapsed time; 20–35 minutes for the whole generation is a planning
estimate, not a guarantee. GPU allocation, cold shader compilation and retries
can change it. Do not multiply the old five-camera pilot's timing linearly.

At the end, `DATASET_PUBLISHED` must report 1,200 images and verified remote
files. A GPU exit code alone is not dataset acceptance. Review the contact sheet
and a selection of close, rear, side and occluded frames as well.

## Asset and annotation contract

- Three detector classes, in order: **0 drum, 1 corrosion, 2 bulge**. This is an
  isolated detector map; the existing hall's `spill` mapping is unchanged.
- All current studio assets are painted LLW drums: nominal 598 mm outer diameter,
  880 mm height. Normal rusted, bulged clean and bulged rusted appearances follow
  `docs/barrel_design_handoff.md`. Include a normal clean control too.
- Bulging varies mildly: 7–9% peak local radial scale, 65–75 mm lid rise above
  the recessed lid. The reviewed reference is 8% / 70 mm. These are not severity
  categories or evidence of measured gas pressure.
- Rust uses separate 0.35 mm conforming chipped oxide geometry. Random seeds and
  circumference shifts preserve the reviewed brown oxidation style. Paint wear
  without oxide is a negative control, not rust.
- Printed A01–D07 warning plates are assigned independently of faults. Reuse the
  yellow/black shared artwork; leading zeroes stay. IDs are metadata, not detector
  classes. Plate caches are invalidated only inside each worker's container.
- 60% close inspection frames and 40% wider context frames: **720/480** images.
  Seeded scenes contain 4, 6 or 8 drums, with variable visible counts. Camera
  bearing, distance, height, lights, room palettes, layout and clutter vary.
  All labelled drum/defect roots remain continuously visible in USD: repeated
  hide/show caused native annotation IDs to disappear despite visible RGB in a
  failed first attempt. Close inspection frames include neighbouring drums and
  require the target to be annotated; planned centre rays avoid other drums.
  Context views require at least two annotated drums and include occlusion.
- Each visible drum has a box. Bulged drums also have one overlapping whole-drum
  condition box. Rust boxes represent local visible patches, grouped within each
  drum before small-box filtering. No invisible proxy is added to force a box.
- Camera: 640×640 RGB, fx=fy=400, cx=cy=320, 22.5 mm focal length / 36 mm aperture.
  Single views 1.0–1.5 m; context 2.8–3.7 m; height 0.45–0.8 m.
- End-on context views with fewer than two visible drums are rejected and the
  bearing is adjusted by 30 degrees, at most three retries. Rejected raw captures
  are separate from accepted frame directories; no fabricated labels are used.

## How outputs are combined and stored

Every worker writes only `/pilots/RUN_ID/seed_NNNN/` within `detector-data`.
Local copies land in `out/detector_pilot/RUN_ID/`. `generation.json`, written before
rendering and persisted remotely, records the frozen plan, source-file hashes,
git commit, GPU and workspace. No generated scene overwrites the hall USD files
or `sim/drums.json`.

The local publisher combines the completed scene directories into:

```text
out/detector_releases/barrels_v2_1200/
  data.yaml
  manifest.json
  generation.json
  images/{train,val,test}/seed_NNNN_frame_NNN.jpg
  labels/{train,val,test}/seed_NNNN_frame_NNN.txt
  metadata/{train,val,test}/seed_NNNN_frame_NNN.json
```

There are **900 train / 150 validation / 150 test** images. Each YOLO label row
is `class x_center y_center width height`, normalised to 0–1. Metadata includes
actual camera/environment parameters, identities, rust seeds, deformation,
native boxes and annotation grouping. Metadata is not input to the detector.
The exporter rejects missing/extra frames, failed scenes, duplicate images,
invalid boxes/classes/calibration, missing inspection targets, missing split classes
and rust seeds crossing split boundaries. It builds into a new temporary directory
and publishes only a complete release. Existing releases cannot be overwritten.

The final destination is **`detector-data:/releases/barrels_v2_1200/`**, environment
`main`, workspace `paramsachdeva07`. Upload checks every recorded remote image,
label and metadata file against its SHA-256 hash and writes a local upload receipt.
To train later, mount the Volume and pass the absolute path to its `data.yaml`.
The portable YAML uses relative dataset subdirectories.

## Failure recovery without losing completed work

Do not rerun with a newly generated plan to hide failures. Use the same source
checkout and plan; a source/plan mismatch blocks resume. If local results remain:

```sh
python detector/modal_pilot.py \
  --resume out/detector_pilot/RUN_ID \
  --gpu RTX-PRO-6000 --workers 10 --workspace paramsachdeva07 \
  --publish barrels_v2_1200
```

Completed validated scenes are skipped. Failed local/remote attempt folders are
preserved under separate names before retrying; accepted frames are not reset.
If the local machine was lost, recover first into a new folder:

```sh
python detector/dataset_release.py recover \
  --run-id RUN_ID --output out/recovery/RUN_ID --workspace paramsachdeva07
# Then use --resume out/recovery/RUN_ID with the same options above.
```

If generation finished but publishing failed, use these CPU-only commands:

```sh
python detector/dataset_release.py build \
  --run out/detector_pilot/RUN_ID --output out/detector_releases/barrels_v2_1200
python detector/dataset_release.py upload \
  --release out/detector_releases/barrels_v2_1200 --workspace paramsachdeva07
```

Skip `build` when a valid local release already exists. Upload refuses an existing
remote release; inspect its manifest before choosing a new version name. Do not
force-overwrite or delete an existing release to make a check pass.

## Paste this into a new agent

> Work in agentverse26 on detector-training. Read docs/dataset_generation_handoff.md
> completely. Current authorization is the single-workspace 1,200-image dataset
> on up to 10 RTX PRO 6000 workers in paramsachdeva07. First check whether the run
> or release already exists; monitor/resume instead of launching duplicates.
> Validate all images and publish to detector-data:/releases/barrels_v2_1200.
> Training is a separate task. Preserve team changes and captures. Do not change
> the barrel design or stop other people's apps. The one-image GPU comparison is
> complete and should not be repeated for this run.
