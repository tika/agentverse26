**Full-store mission: all 28 drums, map coverage and live models**

**Current validation status:** the user requested a cut of run
`011259-agent_full_store-9b11` before the full mission finished. Its 1080p MP4 is
149.58 seconds long; the latest checkpoint has 11/28 observation sets complete,
one deferred and 16 pending. Localization drift near the end caused a navigation
timeout. All-28 completion is **not validated**. Preserve this as a prototype;
localization and its fail-safe need fixing before continuing the full round.
The cut is `out/recordings/agentverse26_coverage_cut.mp4`, with the persistent
run bundle under `agentverse-mission-runs:/runs/011259-agent_full_store-9b11/`.

The fixed 28-drum hall and reviewed barrel designs are preserved. This mission
adds route planning across the three aisles, an inspection ledger for every
drum, an estimated-position trail, observation coverage and durable checkpoints.
The original eight-drum demonstration remains available as `agent_yolo_round.py`.

**Run it**

Configure the authenticated YOLO service and external Cosmos endpoint using
[the integration guide](yolo_cosmos_integration.md). The worker needs the private
`drum-inference` Modal secret. External Cosmos configuration is read from the
private Modal Dict configured by `cosmos-config`; a same-workspace Cosmos
deployment or Hugging Face secret is not required for this client.

```sh
python3 -m unittest discover -s sim/tests
python3 tools/hot_hall.py cosmos-config .runtime/cosmos.env
HOT_SPAWN_X=1.3 HOT_SPAWN_Y=2.0 HOT_NO_OPEN=1 python3 tools/hot_hall.py up
HOT_NO_OPEN=1 python3 tools/hot_hall.py run \
  scripts/hot/sensing.py scripts/hot/scenario_lib.py \
  scripts/hot/prepare_robot_visuals.py scripts/hot/presentation_view.py \
  scripts/hot/front_camera_guard.py scripts/hot/yolo.py \
  scripts/hot/agent.py scripts/hot/coverage_mission.py \
  scripts/hot/agent_full_store.py
python3 tools/hot_hall.py down
```

Use exactly one hot worker per workspace because the request queue is shared.
The current camera mechanics and optional two-GPU seven-drum recording are
described in [the front-camera guide](front_camera_recording.md). The large
image is now the rigid body-mounted front sensor; third person is presentation
only. Plate reads use a digital crop from the front image.
Changes to `sim/*.py` require restarting the worker. Hot scripts are transmitted
for every request. The full mission runs until coverage/deferrals are resolved,
a safety stop occurs or its 540-second simulation budget expires. It is not a
32-second fixed patrol. After coverage, the authored scenario introduces a new
heat/gas/hiss event near the last inspected drum to test sensor-driven retreat.
This world event is not provided as an oracle finding to the planner.

**How coverage is measured**

`sim/mission_coverage.py` builds A* routes on a 10 cm grid. The live mission uses
a conservative 70 cm robot clearance radius plus 3 cm margin around drum
footprints/walls. Candidate views use aisle Y=2 for row A, Y=6 for B/C and Y=10
for D. Each drum has viewpoints at X−0.3 and X+0.3 m. CPU checks validate
collision-free routes to all 56 primary/secondary viewpoints. Coordinates are
known inventory geometry; authored fault labels and source strengths are not
planner inputs.

The agent offers Cosmos the nearest reachable outstanding tasks, with route
cost, missing checks and existing evidence. Cosmos's action ID is constrained
by a JSON schema containing the offered IDs. Python still validates the result
and labels any rules fallback. It routes the chosen task and gives velocity
commands to the pretrained Spot policy; Cosmos does not supply footsteps.

The ledger requires a resolved plate identity, a thermal observation and two
spatially distinct visual observations. Viewpoints must differ by at least
35 cm and 12 degrees around the drum. Repeated stationary frames do not count
as another angle. YOLO-backed views also require a sufficiently large drum box,
valid range and confidence. Failed identity/evidence checks are retried with a
bounded budget, then explicitly deferred. Failed navigation has a deadline.

Coverage and condition are separate: a drum can have observation coverage and
still be bad, uncertain or require manual review. ID/thermal/visual evidence is
collected opportunistically, but the two-angle coverage requires deliberate
inspection stops. The map uses cyan for the entire estimated visited trail,
white for the current route, amber for estimated robot pose and drum tiles for
pending/complete/condition state. The active target has a white outline. Ground
truth is retained only for simulator placement/rendering and evaluation; it is
not used as the displayed visited trajectory or navigation estimate.

**Detector limits and the visual fallback**

The existing detector was trained on painted LLW-style drums. A live static
viewpoint probe detected 14/28 target bodies from the primary views and missed
the 12 stainless ILW drums. That probe used the earlier camera mechanics and
is not a validation of the current fixed front sensor. Camera calibration does
not remove that training-domain gap. No replacement model is trained
or silently deployed by this mission.

YOLO runs throughout. If it does not return the active target's body box, the
agent asks the live Cosmos VLM to inspect a central RGB crop. A visible object,
measured foreground depth and two distinct camera positions provide recorded
visual evidence; the source is explicitly `Cosmos RGB visual fallback`.
Null/uncertain or insufficient VLM condition assessments remain marked for
review. Coverage means the required observations were collected, not automated
clearance or proof of a correct classification. RGB view files, YOLO request
logs and `cosmos_visual_checks.jsonl` preserve the distinction.

**Bulge and temperature rule**

The simulator makes the authored bulged barrels warmer. The agent must discover
the bulge from RGB and the temperature from the synthetic LWIR observation.
`screen_visual_pressure()` flags suspected pressurisation only when visible
bulge and corrected surface temperature at least 5°C above ambient are both
present. That threshold is configurable through the existing pressure-screen
settings and is a simulation choice. A cool bulge remains a shape anomaly;
missing heat is not evidence that a drum is safe. Internal gas and pressure are
never reported as confirmed by these cues. Gas/hiss are separate measurements
near the robot. The stop-on-alert policy is retained.

The distinction matters beyond the demo: [OSHA identifies bulging/swelling as
evidence of possible drum pressure](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.120).
The 5°C simulation threshold is not taken from that standard.

**Progress, persistence and outputs**

The worker writes an atomic checkpoint every five simulated seconds and at task
boundaries. The Modal supervisor commits the volume every 15 wall seconds and
again at the end. A sudden termination can lose the uncommitted interval.

```sh
python3 tools/coverage_progress.py RUN_ID
modal volume get agentverse-mission-runs /checkpoints/RUN_ID.json ./checkpoint.json
modal volume get agentverse-mission-runs /runs/RUN_ID ./downloaded-run
```

The run command downloads that directory automatically, including its MP4. Large
videos are transferred through the volume, not serialized into the shared Dict.
`full_store/` contains the report, memory, telemetry, decision trace, checkpoint,
timings and actual physics/policy timing metadata. Additional files include
the visual evidence images and both model request logs. The report card lists
all 28 drums, not only the first 12.

For a restart, load a saved checkpoint into the next request's
`state['coverage_resume']` before `agent_full_store.py`. `FullStoreMission.start`
checks the inventory hash, restores memory/coverage and replans from the known
dock. It does not teleport to the former robot pose. Previous and new trajectory
segments are drawn separately. Simulation timestamps start a new segment.
The map geometry and authored scenario must match the saved run.

All runtime model calls remain synchronous: simulation time pauses during API
requests. Playback is 12 fps; wall execution is slower. The map is a known-map
coverage display, not a demonstration of SLAM or arbitrary obstacle avoidance.
Structured output support follows [vLLM's JSON schema interface](https://docs.vllm.ai/en/v0.11.2/features/structured_outputs/)
and was tested on the deployed Cosmos endpoint.
