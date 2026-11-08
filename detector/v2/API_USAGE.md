# CANIS YOLO26s API: latest experimental and previous default

The **latest experimental model** is YOLO26s continued on the expanded
**2,500-image yellow / blue-teal ILW dataset**. It is used in the recent
warehouse-v3 rigid-camera recordings. The previous 1,500-image model remains
available and is still the default in `selected_model.json` and the Python
client. Read [LATEST_MODEL.md](LATEST_MODEL.md) for pinned version identity,
worker setup, measured comparisons and limitations. Both use the same four
conditions: `normal`, `rust`, `bulge`, `rust_and_bulge`. Nano's API is retired.

**Latest experimental base URL (select explicitly):**

```text
https://paramsachdeva07--canis-yolo26s-expanded-conditiondetector-web.us-east.modal.run
```

`GET /health` and `POST /predict` both require a Modal workspace proxy token:
`Modal-Key: wk-...` and `Modal-Secret: ws-...`. Obtain the credentials privately
from the workspace owner. These are not the Cosmos key or a Modal CLI API key.
No tokens are committed to this repository.

## Python client

The included client needs only Python's standard library. Explicitly set the
URL to avoid its retained previous-model default:

```sh
export CANIS_API_URL='https://paramsachdeva07--canis-yolo26s-expanded-conditiondetector-web.us-east.modal.run'
export DETECTOR_API_URL="$CANIS_API_URL"
export DETECTOR_API_KEY='wk-<private-key>'
export DETECTOR_API_SECRET='ws-<private-secret>'
python3 detector/v2/api_client.py /absolute/path/to/front_camera.png
```

Set `CANIS_API_URL` or `--url` to override the URL. `--confidence` defaults to
0.25. Upload the **robot's front-camera image**, without overlay boxes/text.

## HTTP

```sh
export CANIS_API_URL='https://paramsachdeva07--canis-yolo26s-expanded-conditiondetector-web.us-east.modal.run'
curl --fail-with-body "$CANIS_API_URL/health" \
  -H "Modal-Key: $DETECTOR_API_KEY" \
  -H "Modal-Secret: $DETECTOR_API_SECRET"

curl --fail-with-body "$CANIS_API_URL/predict?confidence=0.25" \
  -H "Modal-Key: $DETECTOR_API_KEY" \
  -H "Modal-Secret: $DETECTOR_API_SECRET" \
  -F 'file=@/absolute/path/to/front_camera.png' \
  -F 'frame_timestamp=2026-11-08T05:00:00Z'
```

The upload limit is 8 MiB and 4,096 pixels per side. Inference uses a 384-pixel
input internally; returned boxes use the **original uploaded image's pixels**.
The API scales to zero after 120 seconds idle, so the first request can take
longer; the Python client allows 180 seconds.

## Response contract

Read **`condition_detections`** for the native four-class result:

```json
{
  "model": "yolo26s",
  "label_schema": "whole_barrel_condition_v2",
  "condition_detections": [
    {
      "class_id": 3,
      "class_name": "rust_and_bulge",
      "confidence": 0.91,
      "bbox_xyxy": [100, 80, 210, 310]
    }
  ]
}
```

This is an illustrative response, not a measured prediction. Class IDs are
`0 normal`, `1 rust`, `2 bulge`, `3 rust_and_bulge`. Each result covers **one
whole visible barrel**, not an individual rust spot. `barrels` also exposes
`corrosion_observed` and `bulge_observed` booleans. `input_sha256` traces the
submitted image; `best_sha256` identifies the exact checkpoint; `run_id`,
`frame_timestamp`, `image`, `latency_ms` and `model_speed_ms` support logging.

The `detections` field is a compatibility projection into the previous
`drum/corrosion/bulge` names. Those fault boxes also cover the **whole barrel**.
**Do not feed their area into code that estimates rust coverage.** Update that
consumer to use the condition booleans. The four-class IDs are different from
the previous three-class detector's IDs.

Visual bulging is a deformation finding. The agent must combine it with its
separate temperature evidence and decision rules; this model does not measure
temperature, radiation, pressure, or gas.

## Version and storage

- Latest comparison: `compare_colors_20261108T053740Z_continued`.
- Dataset: `detector-data:/color_expansions/canis_colors_20261108T053740Z/dataset.zip`.
- Checkpoint: `detector-models:/condition_v2/compare_colors_20261108T053740Z_continued/yolo26s/best.pt`.
- Checkpoint SHA-256: `ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a`.
- Previous default: `selected_model.json` and
  `detector-models:/condition_v2/active.json` still select the previous model.
- Test reports/plots/predictions: the checkpoint directory's `results.json`
  and `evaluation/` subdirectory.

Both the expanded and previous small-model APIs remain deployed. Authenticated
health checks identify the exact comparison and checkpoint; check them before
accepting findings. See [LATEST_MODEL.md](LATEST_MODEL.md) for the previous URL
and full startup verification, [RUN_RESULTS.md](RUN_RESULTS.md) for measured
results and limitations, and
[README.md](README.md) to reproduce generation and training.

Changing the endpoint does not change the warehouse map, robot control, camera,
Cosmos agent or overlay. Configure the serving URL in the worker's secret and
start an owned worker with that configuration; a running container does not
inherit later shell exports. Do not interpret an API deployment as an automatic
switch in every teammate's simulator.
