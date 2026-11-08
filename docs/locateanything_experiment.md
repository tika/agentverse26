# NVIDIA LocateAnything experiment

Branch: `experiment/locateanything-modal`, based on main revision `9f80885`.
This preview uses the existing 28-drum hall. It does not include the later dense
warehouse commits that appeared on remote main during the experiment.

The hosted visual model is NVIDIA's official `nvidia/LocateAnything-3B`, pinned
to revision `c32291ca5e996f5a7a485845b4f57a233936bba0`. It was the only official
LocateAnything variant listed by NVIDIA when checked. Its model-card license
applies; this is a hackathon/research experiment.

The separate authenticated Modal app is `agentverse-locateanything`:

`https://paramsachdeva07--agentverse-locateanything-locateanything-web.us-east.modal.run`

It loads the official weights once using Transformers 4.57.1, PyTorch 2.8,
BF16 and SDPA. The observed serving GPU was an H100. Weights persist on Modal
volume `locateanything-model-cache`. No weights or credentials go into Git.
The service scales to zero when idle. `GET /health` reports model/revision;
`POST /predict` accepts a JPEG file and optional frame timestamp. Both require
the owner's Modal proxy token via `Modal-Key` and `Modal-Secret`.

## Run

```sh
python3 -m modal deploy detector/locateanything/serve.py
python3 detector/locateanything/client.py image.jpg

LOCATE_API_URL=https://paramsachdeva07--agentverse-locateanything-locateanything-web.us-east.modal.run \
HOT_NAMESPACE=agentverse-locate HOT_CAMERA_WIDTH=640 HOT_CAMERA_HEIGHT=360 \
HOT_GPU_COUNT=1 HOT_SPAWN_X=4 HOT_SPAWN_Y=6 python3 tools/hot_hall.py up

HOT_NAMESPACE=agentverse-locate HOT_NO_OPEN=1 python3 tools/hot_hall.py run \
  scripts/hot/sensing.py scripts/hot/scenario_lib.py \
  scripts/hot/prepare_robot_visuals.py scripts/hot/presentation_view.py \
  scripts/hot/front_camera_guard.py scripts/hot/locateanything.py \
  scripts/hot/agent.py scripts/hot/coverage_mission.py \
  scripts/hot/agent_locateanything_demo.py

HOT_NAMESPACE=agentverse-locate python3 tools/hot_hall.py down
```

Existing private credentials are loaded from `.runtime/detector_api.env` by the
client and from `drum-inference` by Isaac. These are workspace proxy credentials;
the experiment uses its own model URL. Configure Cosmos through the existing
private `cosmos-config` mechanism. Main's YOLO app and weights are untouched.

## Evidence and limits

- Raw front camera: 640x360, the same rigid body mount and field of view as the
  main-branch hall. The spectator is 384x216, used only in the recording.
- Recorded overlay: 1280x720. Box drawing happens before display scaling; the
  model receives the original unannotated front frame.
- Three independent grounding queries locate drums, rust and bulging. Returned
  normalized coordinates are converted back to input pixels. Rust and bulge
  regions are associated with detected bodies, then depth/estimated pose match
  them to inventory locations.
- The service echoes the uploaded JPEG's SHA256. The robot checks that hash
  and image dimensions and records the source camera/frame. Boxes are displayed
  only on the source frame, not over later moving images.
- LocateAnything provides **no calibrated confidence score**. Scores remain
  null, with an explicit unscored-proposal flag. Two distinct viewpoints can
  complete observation coverage; this does not establish classification accuracy.
- YOLO inference and Cosmos/segmentation visual-condition fallbacks are disabled
  in this demo. Cosmos still chooses goals and reads plates from front-image
  crops. Thermal, radiation, gas and safety remain separate sensor channels.
- The initial combined prompt over-labelled all four visible drums. Separate
  rust grounding improved that test frame, but bulge grounding still over-called
  normal cylindrical shapes. This model is not a validated replacement for a
  fine-tuned drum-condition detector. Missing detections remain unresolved.

Outputs are persisted on `agentverse-mission-runs` and downloaded under
`out/hot/`. The demo's recording is a model experiment, not proof that its
zero-shot condition classifications are correct.

## Recorded result

Run `035753-agent_locateanything_demo-c10f` produced a 70.25-second 1280x720
MP4. Four targets completed their observation sets, with 68 successful
LocateAnything requests and eight Cosmos decisions; neither API failures nor
planner fallbacks occurred. Median server inference time was 1,199 ms.

The condition result was poor: accumulated proposals marked all four targets
as rust plus bulge. Only C02 matched that authored condition; B01 was bulge-only,
C03 had no authored visual fault and C04 was rust-only. This is a small scene
spot check, not a held-out accuracy estimate. Keep this backend experimental.

Video: `out/recordings/agentverse26_locateanything_preview.mp4`.
Persistent bundle: `agentverse-mission-runs:/runs/035753-agent_locateanything_demo-c10f/`.
The full manifest is `docs/validation/locateanything_preview_20261108.json`.
