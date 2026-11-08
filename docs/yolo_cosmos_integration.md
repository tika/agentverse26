# YOLO + Cosmos integration into the recorded overlay

The 28-drum hall is the selected environment. This branch merges main through
`d027bc3` (inspection memory, job-based action choices and status rings) and
preserves the training/generation code. The dense stacked branch was not merged.

The detector is deployed; see [model API guide](model_api.md). `scripts/hot/yolo.py`
sends onboard RGB JPEGs to the trained API at most every 0.5 simulated seconds.
The API applies fixed confidence 0.25. Depth and estimated pose associate predicted
barrels with the known geometric store map. Duplicate detections of one map drum
become one observation per request. Map association is not a plate OCR result.

YOLO provides visible-corrosion and visible-bulge findings to `agent.py` and its
inspection memory. It supplies no corrosion area percentage or gas measurement.
The simulator's segmentation remains inside the synthetic LWIR sensor backend;
its corrosion mask supplies no visual evidence when YOLO is enabled. Failed
inference leaves visual evidence unavailable rather than silently using truth.
The overlay shows boxes, map associations, API latency, age, errors, inspection
status, sensor values, map/trail and the planner's actual selected action/reason.

## Configuration

Create a private Modal secret named `drum-inference` with `DETECTOR_API_URL`,
`DETECTOR_API_KEY`, `DETECTOR_API_SECRET`. The keys are the owner-issued workspace
proxy credentials for the detector endpoint, not the Cosmos key.

For the teammate's OpenAI-compatible Cosmos service, create a local ignored file
`.runtime/cosmos.env` with mode 0600:

```dotenv
COSMOS_URL=https://tika--agentverse-cosmos-vllm-serve.us-east.modal.run
COSMOS_MODEL=cosmos
VLLM_API_KEY=YOUR_PRIVATE_KEY
```

Use the base URL without `/v1`; the caller appends `/v1/chat/completions`. Configure
the already-running worker with:

```sh
python3 tools/hot_hall.py cosmos-config .runtime/cosmos.env
```

This saves service settings in a private Modal Dict. Before each request the
supervisor writes a private worker file outside captured outputs. No key is
included in Git, video, API responses or request-script source. An invalid key
returns 401 and is recorded as a Cosmos failure; it is not treated as a model decision.

## Run

```sh
HOT_SPAWN_X=3.0 HOT_NO_OPEN=1 python3 tools/hot_hall.py up
HOT_NO_OPEN=1 python3 tools/hot_hall.py run \
  scripts/hot/sensing.py scripts/hot/scenario_lib.py scripts/hot/yolo.py \
  scripts/hot/agent.py scripts/hot/agent_yolo_round.py
python3 tools/hot_hall.py down
```

The scenario authors heat and gas at C04, while the robot discovers observations
from RGB, depth, thermal, gamma, gas and microphone samples. It starts in the LLW
section where the painted training assets apply. The scenario settings are not
passed to the planner. Cosmos receives measured findings and offered actions.
Safety and navigation enforce their existing independent checks.

Outputs go to a unique `out/hot/RUN_ID/` directory: MP4, structured report,
inspection memory, decisions, events, timings, telemetry and detector request logs.
The MP4 uses the existing 1920×1080 overlay at 12 fps with a full-hall bird's-eye map.
Log/API latency is wall time; simulation timestamps advance with physics.

For independent checks while Cosmos authentication is pending:

```sh
HOT_NO_OPEN=1 python3 tools/hot_hall.py run \
  scripts/hot/sensing.py scripts/hot/scenario_lib.py scripts/hot/yolo.py \
  scripts/hot/probe_yolo.py
HOT_NO_OPEN=1 python3 tools/hot_hall.py run \
  scripts/hot/sensing.py scripts/hot/scenario_lib.py scripts/hot/yolo.py \
  scripts/hot/agent.py scripts/hot/agent_yolo_smoke.py
```

The first saves a real hall RGB frame and trained predictions. The second is a
three-second rules-baseline check with Cosmos and plate-model calls explicitly
off. Its recording must not be represented as a Cosmos-driven mission. A full
Cosmos recording still requires successful endpoint authentication.
