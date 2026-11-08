# Selected CANIS drum detector: YOLO26s

The selected model is **YOLO26s**, fine-tuned on 1,500 new-design synthetic
warehouse frames. Its four conditions are `normal`, `rust`, `bulge`, and
`rust_and_bulge`. Nano's API has been stopped; both trained checkpoints and
comparison reports remain saved on Modal.

**Base URL:**

```text
https://paramsachdeva07--canis-conditions-yolo26s-conditiondetector-web.us-east.modal.run
```

`GET /health` and `POST /predict` both require a Modal workspace proxy token:
`Modal-Key: wk-...` and `Modal-Secret: ws-...`. Obtain the credentials privately
from the workspace owner. These are not the Cosmos key or a Modal CLI API key.
No tokens are committed to this repository.

## Python client

The included client needs only Python's standard library. Its default URL is
the selected small model above.

```sh
export DETECTOR_API_KEY='wk-<private-key>'
export DETECTOR_API_SECRET='ws-<private-secret>'
python3 detector/v2/api_client.py /absolute/path/to/front_camera.png
```

Set `CANIS_API_URL` or `--url` to override the URL. `--confidence` defaults to
0.25. Upload the **robot's front-camera image**, without overlay boxes/text.

## HTTP

```sh
export CANIS_API_URL='https://paramsachdeva07--canis-conditions-yolo26s-conditiondetector-web.us-east.modal.run'
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

- Comparison: `compare_20261108T043410Z`.
- Dataset: `detector-data:/datasets/canis_conditions_1500_20261108T043410Z/dataset.zip`.
- Checkpoint: `detector-models:/condition_v2/compare_20261108T043410Z/yolo26s/best.pt`.
- Checkpoint SHA-256: `96bdf7160d7c4f17bf2d36727da51ecbe65f320cfeaa51b543311147db9a031a`.
- Selected-model pointer: `detector-models:/condition_v2/active.json`.
- Test reports/plots/predictions: the checkpoint directory's `results.json`
  and `evaluation/` subdirectory.

Both APIs were checked against four held-out frames before selection:
authentication was enforced, input/checkpoint hashes matched, and predictions
matched the offline evaluation. Only small remains deployed. See
[RUN_RESULTS.md](RUN_RESULTS.md) for accuracy and limitations, and
[README.md](README.md) to reproduce generation and training.

This release does not change the warehouse map, robot control, Cosmos agent,
mission code, or existing detector endpoint. Integrators explicitly select the
new URL and consume its whole-barrel condition contract.
