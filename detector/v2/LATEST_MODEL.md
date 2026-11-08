# Latest CANIS detector — 8 November 2026

Start here when connecting a teammate's simulator or agent to the latest model.
The latest **experimental YOLO26s** was fine-tuned on **2,500 images** and is the
model used in the recent warehouse-v3 rigid-camera and upward-mount recordings.
It is hosted separately from the previous 1,500-image model, which remains the
repository's default. Explicitly select the URL below to use the latest version.

## Exact version

| Field | Latest experimental model |
|---|---|
| Architecture | YOLO26s, whole-barrel condition detection |
| Modal workspace / environment | `paramsachdeva07` / `main` |
| Modal app | `canis-yolo26s-expanded` |
| Comparison ID | `compare_colors_20261108T053740Z_continued` |
| Dataset ID | `canis_colors_20261108T053740Z` |
| Dataset images | 2,500 total: 1,500 yellow LLW + 1,000 blue-teal ILW primary targets |
| Split | 2,000 train / 235 validation / 265 test |
| Checkpoint SHA-256 | `ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a` |
| Label schema | `whole_barrel_condition_v2` |
| Native classes | `0 normal`, `1 rust`, `2 bulge`, `3 rust_and_bulge` |
| Internal inference size | 384 pixels; output boxes use uploaded-image coordinates |

**Latest API base URL:**

```text
https://paramsachdeva07--canis-yolo26s-expanded-conditiondetector-web.us-east.modal.run
```

The similarly named `canis-conditions-yolo26s` endpoint is the **previous** model.
The model name `yolo26s` alone cannot distinguish them: check `comparison_id`
and `best_sha256`.

## Connect without training or deploying anything

Callers need Python and private Modal **workspace proxy credentials** issued by
the endpoint owner. The existing authorized `wk-...` / `ws-...` pair works for
both endpoints. A teammate with access only to another Modal workspace still
needs credentials for this serving workspace. These are separate from Cosmos
credentials and Modal CLI API tokens. Never commit real credentials.

```sh
export CANIS_API_URL='https://paramsachdeva07--canis-yolo26s-expanded-conditiondetector-web.us-east.modal.run'
export DETECTOR_API_URL="$CANIS_API_URL"
export DETECTOR_API_KEY='wk-<privately-issued-key>'
export DETECTOR_API_SECRET='ws-<privately-issued-secret>'

python3 detector/v2/api_client.py /absolute/path/to/front_camera.png \
  --url "$CANIS_API_URL" --confidence 0.25
```

`detector/v2/api_client.py` reads `CANIS_API_URL` or `--url`. The simulator reads
`DETECTOR_API_URL`. Set both as above. Running the client without either URL
override uses `selected_model.json`, which intentionally still selects the
previous model. Exporting a URL locally does not change an existing Modal
container's environment.

Both `/health` and `/predict` require `Modal-Key` and `Modal-Secret` headers.
Allow up to 180 seconds for an idle service's first request; subsequent requests
use the warm model. No local NVIDIA GPU or Isaac installation is needed to call
this API.

## Verify the version before using its findings

Run this from the repository root after setting the environment above:

```python
import json
import os
import urllib.request
from pathlib import Path
from detector.v2.api_client import predict

base = os.environ["DETECTOR_API_URL"].rstrip("/")
key = os.environ["DETECTOR_API_KEY"]
secret = os.environ["DETECTOR_API_SECRET"]
expected_sha = "ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a"
request = urllib.request.Request(
    base + "/health",
    headers={"Modal-Key": key, "Modal-Secret": secret},
)
with urllib.request.urlopen(request, timeout=180) as response:
    health = json.load(response)
assert health["comparison_id"] == "compare_colors_20261108T053740Z_continued"
assert health["dataset_id"] == "canis_colors_20261108T053740Z"
assert health["best_sha256"] == expected_sha
assert health["label_schema"] == "whole_barrel_condition_v2"
print("Latest experimental model verified:", health["run_id"])

# Replace with an unannotated image from the rigid front camera.
image = Path("/absolute/path/to/front_camera.png")
result = predict(base, image, key, secret, confidence=0.25)
assert result["best_sha256"] == expected_sha
import hashlib
assert result["input_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
print(result["condition_detections"])
```

Log the response's `run_id`, `best_sha256`, `input_sha256`, source camera path,
frame ID and any crop bounds with each observation. This verifies the actual
weights and image used, rather than inferring a version from a video label.

## Select it for a Modal simulation worker

In the workspace that runs Isaac, create a separate secret so existing users of
`drum-inference` retain their current configuration. Keep this private, ignored
file at `.runtime/drum-detector-expanded.env`:

```dotenv
DETECTOR_API_URL=https://paramsachdeva07--canis-yolo26s-expanded-conditiondetector-web.us-east.modal.run
DETECTOR_API_KEY=wk-<privately-issued-key>
DETECTOR_API_SECRET=ws-<privately-issued-secret>
```

```sh
chmod 600 .runtime/drum-detector-expanded.env
python3 -m modal secret create drum-detector-expanded \
  --from-dotenv .runtime/drum-detector-expanded.env

# For a new owned warehouse worker, using latest main's supervisor:
CANIS_DETECTOR_SECRET=drum-detector-expanded HOT_GPU_COUNT=1 \
  python3 tools/full_hall_report/hot_hall_canis.py up
```

The latest-main `tools/hot_hall.py` supervisor also accepts
`CANIS_DETECTOR_SECRET`. Coordinate ownership before starting a shared queue's
worker. A running worker retains its startup secrets: editing a local dotenv
file, updating a Modal secret or pulling Git alone will not switch its endpoint.
Restart only your own worker when a configuration change is needed. Use the
existing scene/agent recording guides after configuring the detector; no map,
locomotion, camera transform, Cosmos or overlay changes are required for this
model switch. This does not automatically enable Cosmos.

## Restore the expanded API in another workspace

To serve a verified copy of the expanded checkpoint in another Modal workspace,
upload `best.pt` and its run metadata as `results.json` under
`detector-models:/condition_v2/compare_colors_20261108T053740Z_continued/yolo26s/`.
The checked-in [validation record](../../docs/validation/yolo26s_expanded_20261108.json)
provides the expected checkpoint hash and dataset ID. Deploy with:

```sh
CANIS_MODEL_SCALE=s CANIS_COMPARISON_ID=compare_colors_20261108T053740Z_continued \
  CANIS_API_APP=canis-yolo26s-expanded modal deploy detector/v2/serve.py
```

Use a proxy token from the new workspace and the URL printed by the deploy
command. Save them as the three `DETECTOR_API_*` fields in the worker's Modal
secret.

## Read the response correctly

Use `condition_detections` or the condition booleans in `barrels`. Every native
box covers a whole visible barrel. The compatibility `detections` list uses
`drum/corrosion/bulge` names, but its fault boxes also cover whole barrels. They
do not measure rust coverage or patch counts. Old three-class patch-detector
class IDs and metrics are a different contract.

Use the unannotated body-mounted front camera as the inference source. The
latest recordings used a declared center crop from that camera, with detections
mapped back onto the native image. A complete recording frame can be displayed
without changing the model's input crop. The 15-degree mount is a camera test
configuration, not a change to the YOLO weights or a new repository camera
default. Intrinsics, mount rotation and crop coordinates must stay consistent
when projecting boxes and depth onto the map.

Bulging is a visual finding. Temperature, radiation, gas and pressure are
separate sensor channels; the detector does not supply them. Repeated stationary
frames also do not replace the agent's distinct-view inspection requirements.

## Results and limits

Both models were evaluated on the same held-out frames at confidence 0.25 and
box IoU 0.5, including missed targets as failures:

| Target group | Count | Previous model | Latest experimental |
|---|---:|---:|---:|
| Original yellow LLW | 75 | 72/75 (96.0%) | 73/75 (97.3%) |
| Original metallic / blue-teal ILW | 75 | 56/75 (74.7%) | 53/75 (70.7%) |
| Additional yellow LLW | 90 | 89/90 (98.9%) | 90/90 (100.0%) |
| Additional blue-teal ILW | 25 | 16/25 (64.0%) | 17/25 (68.0%) |
| All primary targets | 265 | 233/265 (87.9%) | 233/265 (87.9%) |

The latest model improves these yellow and additional-blue subsets, but
regresses on the original ILW subset. It has not replaced the previous default.
All-box mAP50 / mAP50–95 on this expanded test are **82.9% / 78.3%**; these are
different metrics from primary-barrel condition accuracy. These are synthetic
development results, not measured real-world inspection accuracy. The added
data uses tiers 1–2; brief top-row camera tests do not establish tier-3 fault
accuracy. In the recent two-top-drum trial, yellow was visually cleared and blue
remained suspect; an earlier three-drum run missed a mild bulge.

Training continued from the previous best checkpoint for 20 epochs at learning
rate 0.0001 on one RTX PRO 6000. Training took 68.78 seconds; training plus
evaluation took 76.57 seconds. Warm median / p95 inference was 6.06 / 6.28 ms.
Scene-seed splits were preserved and the training sampler shuffled images.
The expanded candidate was selected using validation results, not test scores.

## Persisted artifacts and previous versions

- Dataset: `detector-data:/color_expansions/canis_colors_20261108T053740Z/dataset.zip`.
- Best weights: `detector-models:/condition_v2/compare_colors_20261108T053740Z_continued/yolo26s/best.pt`.
- Results, comparisons, sampler evidence, train logs and predictions: the same
  model directory's `results.json`, `comparison.json`, `sampler.json`, `train/`
  and `evaluation/`.
- The previous default stays at `detector-models:/condition_v2/active.json`
  and `detector/v2/selected_model.json`. Neither pointer was promoted.
- Previous URL:
  `https://paramsachdeva07--canis-conditions-yolo26s-conditiondetector-web.us-east.modal.run`.
- Previous checkpoint SHA:
  `96bdf7160d7c4f17bf2d36727da51ecbe65f320cfeaa51b543311147db9a031a`.
- The older three-class patch service is historical; see
  [the archived API handoff](../../docs/model_api.md).

Both current four-condition `/health` endpoints returned HTTP 200 with their
respective hashes when checked on 8 November 2026. Service state can change;
verify the hash at startup. Weights, datasets, recordings and credentials stay
on Modal or in ignored local output, rather than Git.

[API contract](API_USAGE.md) · [Versioned test results](RUN_RESULTS.md) ·
[Expanded-color reproduction](COLOR_RETRAIN.md) · [Pipeline and baseline reproduction](README.md)
