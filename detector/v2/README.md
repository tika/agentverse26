# CANIS whole-barrel condition retraining

**Latest model:** start with [LATEST_MODEL.md](LATEST_MODEL.md). The 2,500-image expanded YOLO26s is hosted separately and used in the recent rigid-camera recordings. Explicitly select its API URL. `selected_model.json`, the bare client and bare deploy commands still default to the previous 1,500-image model. The reproduction commands below describe that original 1,500-image pipeline.

This pipeline is isolated from the robot/warehouse implementation on `main`.
Do not overwrite or merge simulation code when updating the detector. Current
release updates only the YOLO pipeline and dataset renderer. The owner selected
YOLO26s; nano's endpoint is retired. See [API_USAGE.md](API_USAGE.md) and
[RUN_RESULTS.md](RUN_RESULTS.md) for the live endpoint and measured results.

## Label contract

| ID | Class | Meaning |
|---|---|---|
| 0 | normal | No authored rust or bulging |
| 1 | rust | Rust, no bulging |
| 2 | bulge | Bulging, no rust |
| 3 | rust_and_bulge | Both |

Each annotation is **one whole visible barrel box**, not an individual rust
patch. Printed location IDs are randomized independently of condition. A
bulge prediction is visual evidence of deformation, not proof of gas or
pressure. The robot's temperature/radiation logic remains separate.

Native images are 384 × 384 with a roughly 77.3° square FOV. Horizontal viewing
angles are sampled across ±60°; lighting/exposure, camera distance, printed
IDs, paint tint, rust patterns, and bulge amplitude vary by seed. Fault shape
and texture come from the exact shared asset pack, not an approximation.
Targets that are too dark, clipped, small or occluded are reframed before
acceptance. Manifests retain the actual accepted pose and all retries.

The dataset includes LLW and ILW drums on tiers 1–2. It is generated against
the pinned asset-pack warehouse for appearance consistency; it does not alter
the current mission's hall, route, camera, Cosmos logic, or sensor code.

## Reproduce generation

Use Python with Modal installed and authenticated in the desired workspace.
Run from the repository root. Accept the NVIDIA Isaac Sim license for use.

For a new Modal workspace, create `detector-data` and `detector-models` volumes
once with `python3 -m modal volume create NAME`. The owner's workspace already
has both. Install/login with Modal before running these commands.

```sh
git fetch origin codex/warehouse-dog-inspection
mkdir -p .runtime/drum-pilot15-assets
git show e4d31c8a323708db4af2f94e4396ca4872457eff:handoff/CANIS_YOLO_DRUM_ASSETS_FOUR_CONDITIONS_V1.zip > .runtime/drum-pilot15-assets.zip
python3 -m zipfile -e .runtime/drum-pilot15-assets.zip .runtime/drum-pilot15-assets
python3 detector/v2/dataset_modal.py
```

Ten independent **RTX PRO 6000 Blackwell** workers each process five scene
seeds and 150 frames. One Isaac process is reused within each worker across
its scenes; the separate interactive/pilot renderer is left running. The first
worker must pass ten frames before the other nine start. A generation failure
blocks assembly and training rather than silently supplying incomplete data.

There are 50 independent appearance seeds: 40 training, five validation, five
test. All views of one generated scene stay in one split: **1,200 / 150 / 150**.
Target counts are 375 per class over the full dataset. Additional visible
neighbours also have boxes, so total annotation counts are larger and need
not be perfectly balanced. No raster overlays are model inputs.

Modal volume `detector-data`:

```text
/datasets/<dataset_id>/
  shards/00..09/         # Raw worker images, labels, manifests, native logs
  release/
    data.yaml
    images/train|val|test/*.png
    labels/train|val|test/*.txt
    manifest.json        # Seeds, target, pose, severity, annotation provenance
    summary.json
    contact_sheet.jpg
  dataset.zip            # Portable YOLO dataset; extract and use data.yaml
  dataset_summary.json   # Includes final ZIP SHA-256
```

YOLO labels contain `class x_center y_center width height`, normalized to
[0, 1]. Dataset assembly checks image/label pairing, bounds, dimensions,
unique image hashes, split counts and disjoint scene seeds.

Download the portable release with:

```sh
python3 -m modal volume get detector-data '/datasets/<dataset_id>/dataset.zip' ./dataset.zip
```

If packaging is interrupted after rendering, reuse the saved shards without
starting any new GPUs:

```sh
python3 detector/v2/dataset_modal.py assemble
```

## Train and compare

```sh
python3 detector/v2/train_modal.py
```

The generator writes `.runtime/condition_dataset.json`; the trainer reads it.
Nano and small use the same data, 384 input, 50 maximum epochs, validation
patience 12, batch 64, seed 42 and augmentation settings. Each trainer gets
**one RTX PRO 6000**, and both run concurrently. Pretrained `yolo26n.pt` and
`yolo26s.pt` are fine-tuned using the existing pinned training image; Isaac's
Python environment is never used for training.

Best checkpoint selection uses validation fitness. Final evaluation reports
held-out test mAP50, mAP50–95, per-class precision/recall, confusion matrices,
whole-target condition accuracy including missed detections, missed targets,
normal false alarms, rust/bulge attribute metrics, category/tier breakdowns,
and warm median/p95 latency. These are synthetic test results, not evidence of
real-world inspection accuracy.

Modal volume `detector-models`:

```text
/condition_v2/<comparison_id>/yolo26n|yolo26s/
  best.pt
  results.json           # Metrics, dataset/checkpoint hashes, hardware, timing
  dataset.json
  hardware.json
  progress.json
  train.log
  train/weights/best.pt
  train/weights/last.pt
  train/results.csv
  evaluation/            # Predictions, metrics, plots, error examples
```

Training is not resumed automatically into an existing completed comparison.
Use a fresh dataset/comparison ID for a genuinely new experiment.

## Progress

```sh
python3 detector/v2/status.py
```

Progress is durable in Modal Dicts `canis-condition-generation-progress` and
`canis-condition-training-progress`. Local run pointers live in ignored
`.runtime/`; logs, contact sheets and downloaded metric reports live in
ignored `out/condition_v2/`. No secrets belong in Git.

## Reproduce the previous default deployment

To consume the latest experimental model, use [the latest-model guide](LATEST_MODEL.md); no deployment is needed. The command below serves the **previous default** selected by `selected_model.json`:

```sh
python3 -m modal deploy detector/v2/serve.py
```

Deployment `canis-conditions-yolo26s` has one RTX PRO 6000 maximum, scales to
zero after 120 seconds idle, and verifies the evaluated checkpoint SHA-256
before loading it. Nano's deployment has been stopped; its checkpoint and
reports remain available for reproducibility. The older three-class detector
is separate and is not silently replaced by this deployment.

For a future comparison, explicit `CANIS_MODEL_SCALE=n|s` and
`CANIS_COMPARISON_ID=compare_TIMESTAMP` environment variables override the
selected defaults. Do not deploy an unevaluated checkpoint.

The deployment command prints each HTTPS base URL. Auth uses a Modal workspace
proxy token, supplied through **Modal-Key** and **Modal-Secret** headers. Obtain
a token privately using `python3 -m modal workspace proxy-tokens create`;
do not use a Cosmos key. Existing workspace proxy tokens can be
reused if authorized. Never paste tokens into docs or commit them.

```sh
export CANIS_API_URL='https://<printed-base-url>'
# Set DETECTOR_API_KEY and DETECTOR_API_SECRET privately in your shell.
python3 detector/v2/api_client.py /absolute/path/to/front_camera.png
```

Or send `POST /predict` with multipart field `file`, optional query
`confidence=0.25`, and optional multipart `frame_timestamp`. `/health` returns
model name, comparison, checkpoint hash, dataset ID and test metrics. Both
routes require the proxy headers.

The main result field `condition_detections` contains the four condition class
IDs, confidence and `bbox_xyxy` in original image pixels. `barrels` provides
`corrosion_observed` / `bulge_observed`. `input_sha256` identifies the submitted
raw frame, and `latency_ms` measures server inference/serialization work.

For compatibility, `detections` projects each result into the previous
`drum`, `corrosion`, `bulge` interface. These boxes cover the **whole barrel**;
never interpret their area as corrosion coverage. Confidence bands at 0.6
are display heuristics, not calibrated safety thresholds. Keep the robot's
front camera as the sole inference source. Changing mission endpoints is a
separate integration step; deploying these APIs does not change the agent.

## Approved 15-image visual pilot

`pilot15.py` renders the four catalog appearances for visual review only.
The same catalog drums recur, so that pilot must not be randomly split and
used as an independent test. The persistent worker can be reused:

```sh
python3 detector/v2/warm_pilot.py up
python3 detector/v2/warm_pilot.py run /absolute/path/to/requested_views.json
```

`up` reuses an already-ready worker. It has a four-hour function timeout.
