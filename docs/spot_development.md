# Spot benchmarks and detector handoff

## Measured on Modal L40S

| Stage | Default RTX | RTX Minimal with viewport disabled |
| --- | ---: | ---: |
| Kit startup | ~38 s | 38.8 s |
| Scene setup | Not measured separately | 5.0 s |
| First camera warning to first render | ~77 s | 76.9 s camera warm-up |
| Dry pass | Not measured separately | 20.8 s |
| Spill pass | Not measured separately | 18.7 s, invalid route |
| Total through Kit shutdown message | 177 s | 160 s, before teardown delay |
| Spill detected and alternate viewpoint reached | Yes | No |

RTX Minimal missed the tracer, and Spot came within 0.14 m of its center.
Keep default RTX for this scenario. The timing report now includes a behavior
check so an invalid pass cannot be mistaken for a speed improvement.

In the Minimal run, each 58-frame pass spent about 16.3 s on physics, 2–4 s
on rendering and camera reads, 0.12 s on perception and planning, and 0.34 s
writing overlays and frames. Per-frame physics stepping is the largest measured
steady-state cost. Preserve the walking policy's exported timestep when testing
a more efficient stepping loop, and compare footage and clearance against the
default run.

A second paper cut was teardown. The benchmark wrote its results, then stalled
after the Kit shutdown message. We recovered the files from the container.
The collector now requests fast exit after flushing its files. Measure that
change on the next run. The Modal runner separately prints subprocess, cache
commit, archive, transfer and extraction times. Keep the simulator loaded across
iterations to avoid repaying startup and first-render cost.

## Proposed TensorRT response contract

The detector gets one timestamped RGB frame and returns zero or more findings
in the input image's coordinate system. Keep the simulator's ground-truth
annotations outside the runtime detector and planner.

```json
{
  "frame_id": 42,
  "capture_sim_s": 5.25,
  "detections": [
    {
      "class": "spill",
      "confidence": 0.73,
      "box_xyxy_px": [120, 110, 210, 175],
      "drum_id": null,
      "distance_m": null
    }
  ]
}
```

Use `drum`, `corrosion`, and `spill` as the three canonical classes. Populate
the drum ID only when there is a runtime association. Populate distance from
aligned depth or floor projection and leave it null when unavailable. A spill
box can provide a conservative floor exclusion region. Keep per-class suspect
and confirm thresholds in versioned configuration. A suspected spill may
already warrant a temporary stop or avoidance.

Log the GPU and engine precision, cold engine load, and warm batch-1 p50/p95 for
preprocessing, inference and postprocessing. Report frame age at planner
receipt separately so queueing and data copies are visible. Compare the engine
against the same held-out data and thresholds used for the source model.

## Cosmos captures

A `decision.json` references raw onboard RGB and records readings, candidate
goals, findings and the reference action. The LoRA job uses the same prompt as
the local planner and filters out blocked goals before training. Current
references come from the deterministic spill demo. They exercise data wiring.
A meaningful training run needs reviewed choices across independent layouts,
including ambiguous findings, competing safe actions and cases that warrant
holding. A one-step check does not establish accuracy.

## Adding sensor payloads

On physical Spot, payloads use the robot's power and data interfaces.
Sensor services provide their data with acquisition timestamps. Synchronize
the payload clock and record where each sensor is mounted relative to the
robot. That lets the system put detections from different sensors on the same
hall map. Use the Isaac simulation clock and known mount poses to follow
the same pattern in the demo.

[Boston Dynamics payload data acquisition](https://dev.bostondynamics.com/docs/concepts/writing_services_for_data_acquisition.html) ·
[Time synchronization](https://dev.bostondynamics.com/docs/concepts/base_services.html) ·
[Coordinate frames](https://dev.bostondynamics.com/docs/concepts/geometry_and_frames)

| Payload | First simulation task | What the planner receives |
| --- | --- | --- |
| Thermal camera | Make an aligned synthetic surface-temperature image. Give one drum a repeatable warm patch and respect occlusion. Compare a drum with its own previous views and with nearby drums. | Surface temperature, change from baseline, image crop and a quality flag. The WIPP analysis modeled about 70 days to runaway and only about a 1 °C wall change at runaway, so visible warming is a scenario to test. |
| Downward camera and swab | Detect a floor patch in RGB and use depth or a floor-plane projection to locate it. Use the existing virtual swab for loose contamination. If simulating pH and conductivity, return those as separate results from a reachable sampling point. | Suspected wet area, possible source drum IDs, sample location and measurement results. |
| Acoustic sensing | Add simulated sustained hiss and short impulse events, with fan, footsteps and impact sounds as controls. Use an acoustic detector to turn short audio windows into timestamped findings. | A candidate acoustic event, confidence, and a bearing only if supported by the sensor. A gas-specific sensor would supply concentration. |

[WIPP technical assessment](https://www.wipp.energy.gov/special/technical_assessment_team_report.pdf) ·
[Sellafield acoustic research](https://www.gov.uk/government/publications/annual-research-and-development-review-202122/annual-research-and-development-review-202122) ·
[Sellafield swab trial](https://www.gov.uk/government/news/new-robot-swabbing-technology-trialled-for-the-first-time-at-sellafield)

Give each finding a timestamp, location, sensor, units and evidence ID.
Associate it with a drum when there is a credible ID or spatial match.
The safety loop keeps checking dose and clearance independently. Cosmos
gets the recent findings and safe options when it needs to choose an action.
Keep raw images, audio and sample readings available for replay and the
end-of-run report.
