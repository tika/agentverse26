# Getting to the first complete inspection bot

**Start by putting the pieces we already have into one run.** Today the
28-drum hall has a stationary sensor demo, and Spot has a separate walking
demo that detects a fluorescent spill and takes another aisle. Give one person
ownership of combining them. Everyone else can build against that same run.

## What we want to watch

Spot starts an inspection in the 28-drum hall. A spill appears while it walks.
Spot detects it, stops short, and takes another aisle. It marks the nearby drums
as possible sources and asks for a closer look. At least one visually clear
viewpoint is ruled out by the simulated radiation reading. At the end we get a
short video, a list of findings by drum ID, and a radiation map that shows
where Spot actually took readings.

Start with the existing tracer detector and rules planner so we can run this
before TensorRT and Cosmos are ready. The handoff is the same in both versions.
Perception provides findings and evidence, safety rules decide what motion is
allowed, and the planner chooses among the remaining options.

## Work to hand out

| Owner | Ask them to do this | Ask them to show you |
| --- | --- | --- |
| **Bot integration and navigation** | Put walking Spot into the 28-drum hall and connect the existing RGB, depth, dose, air temperature and humidity readings to its pose. Use one repeatable route with an alternate aisle. Save readings and decisions as the run goes. | One Modal command that runs a dry control and a spill-plus-hotspot case. Show the detour, the radiation veto, and the end-of-run report. |
| **Scene and barrels** | Give the bot team one repeatable test layout. Add a switchable spill and a separate radiation hotspot. Build a small set of clean, corroded, and bulged drums for detector and depth work. Keep the drum IDs stable. | A before-and-after image for each fault and the layout seed. Keep the authored fault labels available for scoring. |
| **YOLO and TensorRT** | Train the visual detector on raw RGB and separate annotations. Return detections with the frame ID, class, confidence and box. Start with drums, corrosion and spills. | A batch of held-out images with predictions, spill recall and false alarms, and batch-1 TensorRT latency. |
| **Perception, Cosmos and reporting** | Turn detections into locations and candidate drum IDs using camera calibration, depth and pose. Pass the selected evidence and safe options to the planner. Use the existing rules path for the first integration, then plug in Cosmos when model access is available. | A replay where the same observations produce a decision, an evidence trail, and a report. Record planner latency separately from detector latency. |

## What we review together

Run the dry and fault cases in the same Isaac process if possible. The dry
run should reach its inspection point without a spill alarm. The fault run
should detect the patch before entering it, flag candidate drums, and show
which viewpoint the radiation rules blocked. A nearby drum stays a suspected
source until the evidence supports attribution. Check that the robot holds
when there is no safe route.

For each review, ask for the clip, event log, report, and timings for startup,
first camera frame, and the episode. The existing warm worker is a fixed
walking preview. Have the integration owner make the shared scenario runnable
from the current checkout so the team can reproduce it on Modal.

## Add these once the shared run works

- **Better drum measurements.** Use depth from repeat views to estimate bulges
  against a reference. Use close-up RGB and masks for visible rust area.
  Metric depth gives distance. Optical depth of field is camera blur.
- **Directional gamma.** Connect the existing bearing bins. Show a sector of
  uncertainty and use repeated observations before estimating a source.
- **Thermal and swab.** Check the pinned Isaac build for thermal support. A
  synthetic surface-temperature image is enough for a first test if it respects
  occlusion and is labeled as simulated. Give the existing virtual swab a
  visible tool marker and require safe reach and a stationary robot. Report
  alpha and beta/gamma separately. A positive swab describes the sampled
  surface, and source attribution remains a separate finding.
- **Chloride and flammable gas.** Research a simulated coupon or surface sample
  for chloride. Pick a target gas before modeling a gas-specific detector.
  Keep both out of the first demo unless they change an inspection decision.

Cosmos gets selected frames, recent readings, findings, and safe choices during
the run. The detailed report comes afterwards. Incremental logs preserve the
evidence collected so far. The first demo can use those files without a live
telemetry service.

[Team run commands](team_quickstart.md) ·
[Existing sensors and criteria](sensors_and_criteria.md) ·
[Detector contract and timings](spot_development.md) ·
[Isaac sensor documentation](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/learn/sensors_and_physics.html)
