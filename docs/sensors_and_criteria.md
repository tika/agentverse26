# Sensors and inspection criteria: implemented extension to Step 2

See the [inspection source register](inspection_source_register.md) for the
verified references, original scope of the numbers, and simulation choices.

The fixed 28-drum layout is preserved: D01–D16 remain 200 L LLW and D17–D28
remain 500 L ILW, at the original positions. The supplied criteria document's
example 60-drum layout is deliberately not used. Its ILW-only premise is also
not imposed on the existing mixed-category scene. These common inspection
thresholds are demonstration settings for both categories; waste category is
inventory metadata, never inferred from external radiation readings.

All numeric thresholds in the executable configuration are **simulation policy**.
They are not a radiation-protection assessment or validated store operating
limits. The supplied document is archived in `inspection_criteria_source.txt`;
its regulatory and scientific references have not been independently verified
for this implementation. Its outstanding questions remain outstanding.

## Run and inspect

From the repository root, with Modal authenticated:

```bash
python3 -m unittest discover -s sim/tests -v
python3 tools/run_drums.py
python3 tools/run_sensors.py
```

The last command uploads `sim/`, runs Isaac on an RTX-capable Modal GPU,
downloads `sim/scene_sensors.usda` and `sim/out/sensors/`, then releases the GPU.
It preserves `sim/scene_drums.usda` as the Step 2 snapshot. No GUI runs.
Open the sensor RGB PNG, depth preview and JSON report in `sim/out/sensors/`.
Raw `distance_to_image_plane_*.npy` is optical-axis depth in metres;
`distance_to_camera_*.npy` is Euclidean range in metres. PNG brightness is only
a preview: nearer is brighter, values beyond 8 m saturate to black, as do invalid
pixels. Use the raw arrays for geometry. The camera's clipping range is 0.05–40 m.

## Implemented sensors

| Sensor | Implementation and output | Present limitation |
| --- | --- | --- |
| RGB | Actual RTX-rendered 640×480 camera, 24 mm focal length | Stationary sensor rig; detector and OCR not trained yet |
| Depth | Same render product, registered metric depth and range arrays | General drum segmentation and diameter reconstruction remain to build |
| Gamma dose rate | Python sum of source strength / squared 3D centre distance, plus 0.2 µSv/h background and 10% Gaussian noise | Toy model; no material-specific attenuation, scatter, dose calibration or energy spectrum |
| Dosimeter | Trapezoidal integration of sampled µSv/h over simulation seconds, divided by 3,600,000 for mSv | No exposure accounted before first sample; sample each simulation tick |
| Swab | Spatial floor contact within 8 cm of a drum perimeter; result after 10 simulation seconds | Virtual tool action; no arm/contact physics or physical sample collection yet |
| Temperature / humidity | Noisy scalar readings from zone A/B; water-ingress hook adds 25 percentage points RH | No fluid, thermal or humidity transport simulation |
| Directional gamma (stretch) | 16 robot-relative azimuth bins with three-bin blur | Optional synthetic output; not a physical gamma camera |

The sensor rig lives at `/World/SensorRig/RGBDepth` for validation. It has no
visible camera housing. Its initial position is (12, 1.9, 0.85), looking at
(12, 3.45, 0.6). Once the dog is added, make the rig a child of the robot and
supply a **local** camera pose. `create_sensor_rig`'s current pose is relative to
its parent, so reparenting without changing the pose is not sufficient.

The existing `source_strength` values (1 LLW, 20 ILW) remain unchanged. For this
model they mean the unshielded contribution in µSv/h at 1 m **from the source
centre**, not activity in Bq and not an empirically established dose for that
waste category. A source is placed at the drum centre at half drum height.
Distance is clamped to 0.1 m to avoid singularities. Each other finite drum
cylinder intersecting the source-to-sensor segment halves its contribution.
Walls, floor and contents are not attenuation volumes. Do not infer waste
category or an individual drum's shielding condition from the summed reading.

## Inspection criteria

`sim/inspection_config.json` is the shared source for thresholds, sensor
parameters, operating limits, event values and decision timing.
`sim/criteria.py` receives **measurements only**. It never reads `drums.json`.
The aggregate condition is the worst known zone; missing fields prevent a clean
all-clear. Missing or low detector confidence requests reinspection.

| Indicator | Ideal | Tolerable | Failing |
| --- | --- | --- | --- |
| Visible rust area | <1% | 1–10% inclusive | >10%, or any measured rust at lifting features |
| Diameter increase vs nominal reference | <2% | 2–5% inclusive | >5% |
| Containment | No visible leak | Residue; swab requested if absent | Puddle or alpha >0.4 / beta-gamma >4 Bq/cm² |
| Shielding change | −20% to <+20% | +20% to +100%, or unexpected fall below −20% | >+100%, or peak dose >100 µSv/h |
| ID | Readable | Partly readable | Unreadable |

The document overlaps at exactly +20%; this implementation uses Tolerable at
+20%, matching its first-trigger table. Unexpected decreases are flagged for
reinspection rather than treated as improved shielding. Boundary choices are
explicit and tested. Corrosion and diameter are percentages, not fractions.
Swab values exactly at threshold are not above threshold. A residue without a
swab is provisional, never a confirmed contamination measurement.

Shielding comparison requires `dose_reference_matched=true` and a stored
baseline measured at the same reference pose, nominally 1 m from the drum
surface. A reading taken nearer a drum is not compared directly with a farther
baseline. The present backend does not separate overlapping sources into
per-drum measured dose. An inspection routine must revisit a saved pose and
compare the total reading under comparable scene conditions.

Ideal → log and continue. Tolerable → inspect a second angle and flag the next
shift. Failing → stop, capture best-angle evidence, alert and request routing
around the aisle; request a swab if a leak is suspected and it can be performed
safely. These are structured **action requests**, not an implemented locomotion
controller. The eventual navigation/safety executor must enforce them.

Environment flags: temperature outside 5–25 °C, RH >60%, or a detector reporting
standing water away from a drum. Humidity cannot distinguish water ingress from
a drum leak; camera evidence supplies that distinction.

## Hard safety rules

`safety_decision` consumes timestamps, measured dose, integrated dose, a
measured/estimated nearest drum surface distance and optional person distance.
It returns an action, evidence codes, map colour and optional speed cap.

- Camera or dose absent/stale for >2 s → stop and report the dropout.
- Nearest drum distance unavailable or <0.5 m → stop. A swab moves a virtual
  tool; it never permits the chassis to cross this limit.
- Approaching a drum at ≤1 m → stop to inspect.
- Person <2 m → stop.
- Dose >100 µSv/h → request backoff to the last safe waypoint, mark red.
- Integrated dose ≥40 mSv (80% of 50 mSv) → request return to dock.
- Within 2 m of drums → cap commanded speed at 0.5 m/s.
- Dose >7.5 µSv/h → amber, or red above 100; otherwise green.

If rules conflict, an immediate stop outranks return, which outranks backoff.
An executor must resume the safe return/backoff after the blocking condition
clears. There is no AI override for hot-zone entry. Map colours describe the
simulation policy; they do not establish a legal controlled-area designation
from an instantaneous reading. At the simulated µSv/h rates the 40 mSv return
threshold will not normally trigger in a short demo; its boundary is tested
with fixture readings, not falsely presented as observed mission exposure.

The confidence band 0.4–0.7 is configurable; below 0.7 requests reinspection,
including scores below 0.4. Cosmos is not loaded at this step. The future loop
should call it on new detections, zone changes or failed rules, record latency
against the 2 s target and let hard rules operate without waiting for it.

## Information boundary and next integration

`SensorWorld` privately owns a copy of world inventory and contamination state.
`sample`, `gamma_bins` and `poll_swab` emit readings, timestamps and spatial
contact only; they do not reveal drum IDs, conditions, source positions or
individual source strengths. `inject_leak` and `inject_water_ingress` are
simulator-only hooks. A future agent process receives camera arrays and these
packets, with no inventory file mounted. Keeping fields private in Python alone
is not a security boundary; process/file separation must be added with the agent.

`agent_observation.json` is a real captured packet. The report's ROI depth
measurement and rule example demonstrate the API, but the ROI is not yet a
validated estimator of nearest drum distance for a moving robot. Never substitute
known drum coordinates for that missing perception component.

Next steps remain: visible faults and semantic labels/dataset generation,
YOLO/OCR and depth measurements, then dog locomotion, safe navigation, agent
memory/planning and decision evidence logging. All 28 drums are still visibly
clean in this step. Leak/swab and humidity event hooks have behaviour tests;
they do not yet add visible puddles or change drum geometry.
