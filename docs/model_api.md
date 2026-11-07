# Trained drum model API

The deployed YOLO26s endpoint is:

`https://paramsachdeva07--agentverse-drum-detector-api-drumdetector-web.us-east.modal.run`

It serves `best.pt` from run **`yolo26s_20261107T225757Z_d625ef`**, trained for
40 epochs on one RTX PRO 6000 after the eight-H100 request remained queued.
Training took 266.34 seconds; the training-node function took 278.27 seconds.
The model is pinned by SHA256
`63dc5dfd9933aff58bc0cfc5a759de4b78ef9f25b6c7b74f3f818bceb72e6f04`.

## Call it

All routes require a Modal workspace proxy token. In this local checkout,
`source .runtime/detector_api.env` loads private credentials already provisioned
for the API. That file is ignored by Git and has mode 0600. The endpoint owner
must privately issue credentials to teammates, or a teammate with access to the
`paramsachdeva07` workspace can create a token in that workspace with
`modal workspace proxy-tokens create`. Tokens from unrelated Modal workspaces
will not authenticate here. Allow the token in `main` if the workspace uses
environment-scoped tokens. Do not paste
credentials into source code, Markdown, logs or a browser frontend.

Set `DETECTOR_API_URL` to the URL above, `DETECTOR_API_KEY` to the token ID and
`DETECTOR_API_SECRET` to its secret. A client needs Python only; it does not
need a GPU, Isaac Sim, PyTorch or a Modal account when it has valid API credentials.

```sh
python3 detector/api_client.py /absolute/path/to/frame.jpg
python3 detector/api_client.py /absolute/path/to/frame.jpg --confidence 0.5
```

Or call directly:

```sh
curl --fail-with-body "$DETECTOR_API_URL/predict?band=fixed&confidence=0.25" \
  -H "Modal-Key: $DETECTOR_API_KEY" \
  -H "Modal-Secret: $DETECTOR_API_SECRET" \
  -F 'file=@frame.jpg' -F 'frame_timestamp=sim-frame-123'
```

Python with `requests`:

```python
import os, requests
with open('frame.jpg', 'rb') as frame:
    response = requests.post(
        os.environ['DETECTOR_API_URL'] + '/predict',
        headers={'Modal-Key': os.environ['DETECTOR_API_KEY'],
                 'Modal-Secret': os.environ['DETECTOR_API_SECRET']},
        files={'file': ('frame.jpg', frame, 'image/jpeg')},
        params={'band': 'fixed', 'confidence': 0.25}, timeout=180,
    )
response.raise_for_status()
observation = response.json()
print(observation['barrels'])
```

## Response and operating modes

The default is **`band=fixed`, confidence 0.25**, matching the barrel audit below.
Each response contains model/run/checkpoint IDs, image dimensions, timestamp,
applied thresholds, timing, raw `detections` and grouped `barrels`.

- Raw classes: **0 drum, 1 corrosion, 2 bulge**. Each detection has confidence and
  pixel `bbox_xyxy`. Corrosion boxes represent patches; drum/bulge boxes cover a drum.
- Grouped barrels have a frame-local ID, box, drum confidence,
  `corrosion_observed` and `bulge_observed`. Association uses the predicted boxes,
  not simulator IDs. These frame-local IDs are not inventory plate IDs.
- Optional `band=suspect` or `band=confirm` uses the original validation-calibrated
  class thresholds. Corrosion's suspect threshold 0.01 produces many false patch
  alerts; its confirm threshold 0.72 misses most patches. Those profiles optimize
  patch-box targets, not barrel condition decisions. Use the documented fixed
  profile for comparison with the barrel audit.
- `confidence=...` overrides the profile with one threshold for all three classes.
- JPEG, PNG or WebP; maximum 8 MiB, 4096 px per side. A missing upload returns 422,
  unsupported format 415, oversized image 413. Missing credentials return 401.
- `GET /health` reports the pinned weights, actual GPU and thresholds. `/docs`
  and `/openapi.json` are also protected by the gateway's authentication.

2D condition association can confuse overlapping barrels; use depth and temporal
tracking in the robot. Rust/bulge observations do not measure radiation, gas or
pressure. Fuse those separate sensor observations in the agent.

## What the tests actually measured

The held-out test has 150 synthetic images, 46 distinct scene drums and 567
visible barrel appearances. Five appearances with rust enabled but no visible
annotated patch are excluded from rust-condition accuracy.

| Test result, fixed confidence 0.25 | Count |
|---|---:|
| Real barrel appearances detected, IoU >= 0.5 | 555 / 567 (97.9%) |
| Extra predicted drum boxes | 15 |
| Visibly rusty appearances flagged | 251 / 259 (96.9%) |
| Clean appearances falsely flagged rusty | 2 / 303 (0.7%) |
| Rust and bulge status both correct, including detection | 500 / 562 (89.0%) |
| Rusty appearances in that fully correct group | 237 |
| Patches localized on those 237 appearances | 1,221 / 2,908 |
| Patches missed or below IoU 0.5 on those appearances | 1,687 / 2,908 (58.0%) |

Rust recognition is much stronger than exhaustive patch localization. On all test
images the standard box mAP50 / mAP50–95 is 79.26% / 64.59%; per-class mAP50 is
98.26% drum, 43.76% corrosion patch, 95.76% bulge. mAP is not the fraction of
barrels correctly classified. These are synthetic studio results, not measured
real-world or full-hall accuracy. Repeated views are not independent barrels.

The API smoke test verified authenticated real inference, rejected unauthenticated
access, rejected a missing upload, checked checkpoint identity, and checked the
default profile/grouped response. See the committed results under
`docs/validation/yolo26s_20261107T225757Z_d625ef/`.

## Storage, deployment and reproduction

Weights, optimizer-bearing recovery checkpoint, configuration, predictions, plots,
test metrics, barrel audit and API smoke results are in
**`detector-models:/runs/yolo26s_20261107T225757Z_d625ef/`** in workspace
`paramsachdeva07`, environment `main`. Large weights and credentials are not in Git.

```sh
DETECTOR_MODEL_RUN=yolo26s_20261107T225757Z_d625ef \
  python3 -m modal deploy detector/serve_yolo26s.py --env main
```

Hosting requests one L4 with RTX PRO 6000 fallback, maximum one container,
minimum zero, idle timeout 60 seconds. A cold request can take longer than warm
inference. Stop the deployed app with `modal app stop agentverse-drum-detector-api --yes`
if no longer needed. The training and evaluation workers have stopped.

See [training and serving handoff](yolo26s_training_serving.md) for the full recipe.
The barrel audit can be reproduced without a GPU using `detector/barrel_audit.py`
and the frozen `evaluation/test/predictions.json` plus released image metadata.
