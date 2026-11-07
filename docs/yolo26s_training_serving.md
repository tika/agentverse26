# Train and call the drum detector

This trains **one YOLO26s**, with all eight H100s jointly updating its weights.
It does not train eight candidates. Inputs are the frozen 1,200-image release
`detector-data:/releases/barrels_v2_1200` in Modal workspace `paramsachdeva07`,
environment `main`: 900 train / 150 validation / 150 test. Scene seeds do not
cross splits. Classes are **0 drum, 1 corrosion, 2 bulge**. Printed inventory IDs
are randomized appearance, not prediction classes. Rust and bulge can overlap a
drum box; associate faults to drums spatially instead of counting them as extra
physical drums. This is box detection, not segmentation or gas measurement.

## Prerequisites

Use a normal Python environment with `modal==1.6.3`, authenticate to the workspace,
and check `python3 -m modal profile list --json`. Do not install these dependencies
into Isaac Sim's Python. The Modal image installs PyTorch 2.9.1+CUDA12.8,
torchvision 0.24.1 and Ultralytics 8.4.207. No dataset generation is needed again.

## Run training and monitor

From the repository root:

```sh
python3 -m unittest detector.test_evaluation_metrics detector.test_release
python3 -u detector/modal_train.py
```

The runner prints the run ID and Modal app URL. It requests `H100:8` on one
machine, verifies eight GPUs and all eight distributed ranks, verifies the
archive and every dataset file hash, then trains at 640 px/global batch 64,
AdamW lr 0.001, AMP, seed 42, up to 40 epochs, patience 10. Mild colour,
translation, rotation, scaling and horizontal-flip augmentation are recorded in
`train/args.yaml`; mosaic/mixup/vertical flips are disabled. Each epoch prints
metrics, elapsed time and a rolling ETA, and commits progress/checkpoints.
No GPU rendering is required during training.

In a second terminal, read progress without allocating another GPU:

```sh
python3 detector/training_status.py
# Or supply the explicit run ID to inspect an older run.
```

After training, the eight-H100 worker exits. A separate L4 worker calibrates
suspect/confirm confidence thresholds **using validation only**, then evaluates
the 150 test images. The highest validation fitness selects `best.pt`. Test
scores never choose weights or thresholds. The runner downloads small reports
and plots to `out/detector_training/RUN_ID/`. Its stdout/log is also useful if an
exception occurs; remote `training.log` preserves rank errors.

## Persistent bundle

All these paths are in **`detector-models:/runs/RUN_ID/`**:

- `best.pt`, `last.pt`: final selected and final epoch checkpoints.
- `resume_last.pt`: optimizer-bearing checkpoint saved before the library strips
  optimizer state from final inference weights; retained for recovery.
- `run_manifest.json`, `hardware.json`, `ranks/`, `training_runtime.json`:
  dataset/source fingerprints, versions, actual GPU inventory, eight-rank proof,
  and measured runtime.
- `progress.json`, `epoch_events.jsonl`, `training.log`, `train/results.csv`,
  `train/args.yaml`, plots and periodic checkpoints.
- `thresholds.json`: validation-derived operating points and flags saying whether
  90% recall / 90% precision targets were achievable. A fallback threshold is not
  a promise that its target was achieved.
- `evaluation/results.json`, `evaluation/results.md`: test mAP50, mAP50–95,
  per-class precision/recall and fixed-threshold TP/FP/FN/false alarms per image.
- `evaluation/val/`, `evaluation/test/`: complete predictions, confidence curves,
  confusion matrices and annotated batches; `evaluation/test_examples/` contains
  selected actual predictions including difficult images.

Download the weights when needed:

```sh
python3 -m modal volume get detector-models /runs/RUN_ID/best.pt ./best.pt --env main
python3 -m modal volume get detector-models /runs/RUN_ID/evaluation ./evaluation --env main
```

Scores describe held-out synthetic studio images. They do not establish real
camera accuracy, full inspection-hall accuracy, gas pressure, radiation or safe
operation near radioactive material. Corrosion labels include many small patches;
their box recall is different from the fraction of rusty drums discovered.

## Deploy the authenticated API

Only deploy a run with a successful `evaluation/results.json`:

```sh
DETECTOR_MODEL_RUN=RUN_ID python3 -m modal deploy detector/serve_yolo26s.py --env main
```

The resulting HTTPS URL is the API base. It loads the exact `best.pt` whose SHA256
matches the evaluation report. One L4 serves it, minimum containers 0, maximum 1,
idle timeout 60 seconds. Cold requests start the GPU/container; model inference
timings exclude cold start and network. Model export/engine optimization is
optional later work. An H100 TensorRT engine would not be portable to every GPU.

All routes require a **Modal workspace proxy token**, including `/docs` and
`/health`. Create one privately, keep both values outside Git, and set:

```sh
python3 -m modal workspace proxy-tokens create --name drum-detector-client
# If workspace RBAC is enabled, allow the token in main:
# python3 -m modal workspace proxy-tokens allow wk-YOUR_ID main
export DETECTOR_API_URL='https://YOUR_DEPLOYMENT.modal.run'
export DETECTOR_API_KEY='wk-YOUR_ID'
export DETECTOR_API_SECRET='ws-YOUR_SECRET'
python3 detector/api_client.py /absolute/path/to/camera_frame.jpg
```

If this session created `.runtime/detector_api.env`, it is a private, ignored file
with mode 0600: `source .runtime/detector_api.env` sets those three variables.
Do not commit it or share screenshots containing its contents. New collaborators
should create their own credentials. Delete/revoke unused proxy tokens through
Modal. Proxy token permissions belong to the workspace/environment, not one URL.

Equivalent request from Python:

```python
import os
import requests

with open('camera_frame.jpg', 'rb') as image:
    result = requests.post(
        os.environ['DETECTOR_API_URL'] + '/predict',
        headers={'Modal-Key': os.environ['DETECTOR_API_KEY'],
                 'Modal-Secret': os.environ['DETECTOR_API_SECRET']},
        files={'file': ('camera_frame.jpg', image, 'image/jpeg')},
        params={'band': 'suspect'},  # or confirm; optional confidence overrides thresholds
        data={'frame_timestamp': 'simulation-frame-123'},
        timeout=180,
    )
result.raise_for_status()
print(result.json())
```

`POST /predict` accepts JPEG/PNG/WebP up to 8 MiB and 4096 px per side. It returns
the run ID, checkpoint hash, dimensions, frame timestamp, `detections` with
`class_id`, `class_name`, `confidence`, pixel `bbox_xyxy`, suspect/confirm band,
and timing. `GET /health` identifies the pinned model. `/docs` is interactive
OpenAPI documentation, with the same proxy-auth headers required at the gateway.
Class-aware predictions retain overlapping drum/bulge boxes.

For the robot, encode RGB frames to JPEG and call at a bounded rate asynchronously.
Associate boxes with depth to locate observations; fuse temperature and simulated
radiation separately. Let the agent choose closer inspection, avoidance and
replanning. Avoid requesting inference on every rendered frame or blocking the
simulator's physics loop. The API does not decide whether a drum contains gas.

## Code map

- `training_image.py`: pinned isolated dependency image.
- `modal_train.py`: eight-GPU orchestration, hash validation, persistence and L4 evaluation.
- `train_yolo26s.py`: eight-rank torchrun entry point and checkpoint/progress callbacks.
- `evaluation_metrics.py`, `evaluate_yolo26s.py`: validation calibration and held-out metrics.
- `training_status.py`: read-only progress query.
- `serve_yolo26s.py`, `api_client.py`: authenticated deployment and camera-image client.

Source and reports belong in Git; datasets, checkpoints, API secrets and generated
bulk outputs stay in Modal volumes or ignored local directories.
