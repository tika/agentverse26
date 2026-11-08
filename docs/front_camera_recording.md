# Fixed front camera and short recording

> For new detector experiments, explicitly select and verify the [latest expanded YOLO26s](../detector/v2/LATEST_MODEL.md). The recording reproduced below is a historical mission and does not automatically switch to new weights. The recent 15-degree upward-mount test was a separate stationary camera/model test; this guide's default calibration and Cosmos mission are unchanged.

The primary sensor is `/World/WalkingSpot/body/FrontCamera`, a child of Spot's
physical body. It inherits translation, roll, pitch, yaw and body height. No
planner or plate reader changes its transform. The recording displays this RGB
image in the large left panel. YOLO receives the original RGB JPEG; Cosmos
receives that same frame or a declared digital crop of it. Plate reading is a
crop, not an independently aimed or optically zoomed camera.

`/World/Presentation/CornerCamera` is the small upper-right spectator. It can
follow the dog for presentation but never supplies detector, VLM, navigation or
thermal evidence. The warehouse map is schematic, not another camera. The
synthetic thermal image is aligned to the primary sensor.

For the approved one- and two-drum tests with the fixed 15-degree upward mount and uncropped CANIS display, use [rigid_camera_demos.md](rigid_camera_demos.md). These tested scripts are separate from the historical mission below.

## Reproduce the seven-drum recording

Configure the private services as in [the integration guide](yolo_cosmos_integration.md).
Use only one hot worker, because its Modal request queue is shared.

```sh
python3 tools/hot_hall.py cosmos-config .runtime/cosmos.env
HOT_GPU_COUNT=4 HOT_SPAWN_X=4 HOT_SPAWN_Y=6 python3 tools/hot_hall.py up
HOT_NO_OPEN=1 python3 tools/hot_hall.py run \
  scripts/hot/sensing.py scripts/hot/scenario_lib.py \
  scripts/hot/prepare_robot_visuals.py scripts/hot/presentation_view.py \
  scripts/hot/front_camera_guard.py scripts/hot/yolo.py \
  scripts/hot/agent.py scripts/hot/coverage_mission.py \
  scripts/hot/agent_seven_drums.py
python3 tools/hot_hall.py down
```

The scope contains seven nearby row-B/C drums, selected from known geometry.
The other 21 remain pending on the map. The mission retains live Cosmos choices,
YOLO, simulated radiation/gas/temperature channels, two-angle evidence checks,
physical body alignment and the existing safety rules. It ends when those seven
are complete/deferred, at a safety stop, or at its 170-second simulation limit.
Reports preserve missing evidence; selecting seven does not guarantee seven
successful inspections. Recordings play at 12 fps; API requests pause simulated
time. The request downloads its MP4, reports, telemetry and model-input logs into
`out/hot/RUN_ID/`; the same bundle is stored in Modal volume
`agentverse-mission-runs:/runs/RUN_ID/`.

Four RTX PRO 6000s are requested with L40S as an allocation fallback. Set
`HOT_GPU_COUNT=1` or `2` for fewer GPUs. Headless viewport updates are disabled, so only
the two requested views render. Extra GPUs can improve rendering but do not
parallelize the robot's sequential decisions or CPU physics. We have not measured
a controlled one-versus-two-GPU speedup. [NVIDIA's guidance](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/reference_material/sim_performance_optimization_handbook.html#multi-gpu-support)
recommends no more GPUs than rendered cameras for this workload.

## Verify the source of the model inputs

Every frame checks the mount against the body's full quaternion, with a 2 mm
position/error bound and a 0.002 rotation-matrix norm bound. The front RGB/depth
arrays have the same dimensions. YOLO responses echo the SHA256 of the uploaded
JPEG; the client verifies it and records the primary camera path, source frame,
raw RGB hash and JPEG hash in `yolo_requests.jsonl`. `model_inputs.jsonl` records
Cosmos's source frame and any crop bounds. No annotated recording frame is sent
back into either model. Boxes are drawn only on their actual source frame, so
2 Hz inference boxes can blink during the 12 fps recording rather than drift
over a later image.

For the short walking/turning camera preflight, use the same libraries through
`agent.py`, then append `sim/body_observation.py`,
`scripts/hot/camera_audit_quick.py` and `scripts/hot/audit_front_camera.py`.
Omit `camera_audit_quick.py` to additionally test physical body pitch and crouch.
The posture controller uses joint targets and physics, not root/camera teleports.
The live posture audit found that this walking policy uses explicit actuators,
which the optional posture controller does not support. Look-up/down/crouch
actions are disabled; they are not offered to Cosmos. The camera still follows
physical body pitch/roll from the walking gait. Inspect/better-view tasks already make
the robot physically turn, approach and change position before capturing.

## Relationship to real Spot

Boston Dynamics documents body sensor frames and image-time transforms in its
[frame guide](https://dev.bostondynamics.com/docs/concepts/geometry_and_frames).
Real Spot has multiple stereo camera pairs rather than this single simplified
forward RGB-D stream; see [Spot specifications](https://support.bostondynamics.com/s/article/spot-specifications).
Our 1280×720 resolution, 110° horizontal field of view and `[0.60, 0, 0.12]` m
body-relative mount are simulation calibration choices, not measured factory
Spot intrinsics/extrinsics. A hardware port must use the actual image source's
lens model/intrinsics and image-time `transforms_snapshot`, as defined by the
[Spot image protocol](https://github.com/boston-dynamics/spot-sdk/blob/master/protos/bosdyn/api/image.proto).
Real Spot supports body height/orientation stand commands; see the
[programming guide](https://dev.bostondynamics.com/docs/python/understanding_spot_programming).
That does not by itself validate this simulator's optional joint-space posture controller.

The previous full-store mission's localization drift is a separate unresolved
issue. This camera correction does not establish reliable all-28 completion.
