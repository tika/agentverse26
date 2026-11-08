# Randomized warehouse inspection sessions

Generate a session each time the robot enters the 420-drum warehouse. The clean
`warehouse-v3.usda` remains the reusable base. A session is a USD overlay plus
the textures it references. Keep them together and keep the source checkout
available at the path recorded in the overlay.

## Launch from Isaac Sim

From the repository root, with Isaac Sim's Python environment:

```sh
/path/to/isaac-sim/python.sh sim/build_environment.py --warehouse-v3
```

The launcher generates a fresh seed, opens the session, applies the existing
`class`, `drum_id` and `waste_category` labels and attaches the existing Spot
camera. It prints the output stage path. The default output is a new directory
under the ignored `sim/out/environment/runs/`. Use `--no-robot` for an empty
robot spawn. The legacy builder retains its existing behavior when invoked
without `--warehouse-v3`.

For a reproducible run, use a fresh output path and keep evaluator truth outside
the robot's observation inputs:

```sh
/path/to/isaac-sim/python.sh sim/build_environment.py --warehouse-v3 \
  --seed 42 --output sim/out/inspection/run-42/warehouse.usda \
  --fault-manifest sim/out/evaluator/run-42.json
```

Autonomy launchers that own their Isaac context can call the same generator.
Put `sim/warehouse-v3` on the Python import path, then call:

```python
from drum_faults import generate_session

session = generate_session(session_dir / "warehouse.usda")
assert context.open_stage(str(session))
# Continue with the team's normal robot spawn, labels and RGB/depth capture.
```

The generator also runs with OpenUSD, NumPy and Pillow without starting Isaac:

```sh
python sim/warehouse-v3/drum_faults.py --output sim/out/inspection/new/warehouse.usda
python sim/warehouse-v3/verify_fault_session.py
```

Use a unique output directory per launch. Seeded runs replay the assignment,
geometry and image bytes with the same code and dependencies. When supplied,
the evaluator manifest lists the seed, affected IDs, generator severity,
corrosion anchors and measured radial displacement. Omitted IDs are clean.
Treat the manifest as evaluator data. Expose RGB/depth and package identity to
the robot, and keep USD internals, paths and evaluator reports out of its
observation interface.

## How the defects are constructed

- **LLW painted steel.** Corrosion concentrates at bottom chimes, underneath
  rolling hoops, near the top chime, along a nominal side seam, and at occasional
  coating damage. Mottled dark red-brown scale and smaller orange areas interrupt
  the yellow paint. Tapered runoff starts at elevated corrosion sites and runs
  down the shell. Deformation swells around mid-height, tapering back to the
  seated upper and lower chimes.
- **ILW stainless design.** More localized, lower-coverage dark pitting and muted
  brown staining concentrate at bottom and rim crevices and at a nominal weld
  line. The warehouse's teal visual finish is retained. The simplified geometry
  has no surveyed weld bead or heat-affected zone. The weld anchor is a modeling
  assumption, and pitting is more likely where deposits retain moisture or
  chlorides. Internal expansion scenarios produce a localized sidewall lobe with
  the rims held in place. The lobe peaks near the middle of the wall.
- **Appearance and geometry.** Corrosion uses base color, roughness, metallic
  response and fine normal relief. The print is retained. Bulges change mesh
  points, silhouette and rendered depth. Distorted drums stay inside their
  existing static rack proxies. Rust and bulging can occur independently or
  together. The training mix and displacement ranges are scenario settings.
  They are not facility prevalence, wall-loss estimates or safety thresholds.

## YOLO26s training alignment

The detector team's frozen `barrels_v2_1200` recipe and published example
images were reviewed from the GitHub `detector-training` branch at
`1c43b4d47a1dd67f346d6d2a8564999f52557dcb`. The LLW generator uses the
reference's chipped oxide scale, dark-brown palette, bottom/rim/hoop bias,
and fine downward streaks. The inspected reference's broad center swelling
also informs the LLW shape. The warehouse uses texture-based oxide and limits
radial expansion to the rack spacing. The studio recipe includes a 65–75 mm
lid dome, which this version does not simulate. This is visual alignment,
not model-in-the-loop calibration. The training set contains LLW drums only.
ILW pitting and localized bulges are out-of-distribution examples.

The published detector contract is `0 drum, 1 corrosion, 2 bulge`. This is
the detector branch's contract and is separate from the legacy simulator's
`spill` class mapping. The exact model is
`yolo26s_20261107T225757Z_d625ef`, SHA-256
`63dc5dfd9933aff58bc0cfc5a759de4b78ef9f25b6c7b74f3f818bceb72e6f04`.
GitHub contains the recipe and reports. The checkpoint is at
`detector-models:/runs/yolo26s_20261107T225757Z_d625ef/best.pt` in the
`paramsachdeva07` Modal workspace. Use the detector team's
[training and serving instructions](https://github.com/tika/agentverse26/blob/detector-training/docs/yolo26s_training_serving.md)
to obtain the checkpoint or use their authenticated service.

## Inspection and evaluation

Use the ID and adjacent aisle in the existing map to schedule observations.
Check the bottom chime and beneath the hoops or rim, then use an oblique view
of the flank to distinguish a bulge from ordinary cylindrical curvature or
specular highlights. Compare aligned depth or silhouette to the nominal drum
profile. Reacquire from a second view when a shelf, lighting, angle or the
fixed camera pitch hides a suspected feature. The fixed first-tier camera
view cannot establish that the rest of a drum is clean. Separate external
corrosion evidence from inferred internal conditions. Rust stains and a bulge
do not establish leakage, internal pressure, corrosion depth or radiological
release.

The Isaac review uses stationary cameras and a static collision test. The
detector and navigation policy remain the autonomy team's integration points.

## Technical sources

- DOE's stored-waste robotics report identifies the side and bottom seams as
  common corrosion initiation sites in its drum population. [DOE OSTI report](https://www.osti.gov/servlets/purl/207474)
- The DOE TRU safety basis standard describes uniform expansion, protrusion
  between rolling hoops and deformation of a rolling hoop as observable bulge
  forms. [DOE-STD-5506-2007](https://directives.doe.doxcelerate.com/documents/doe-std-5506-2007-preparation-of-safety-basis-documents-for-transuranic-tru-waste-facilities)
- Nuclear Waste Services describes the 500 L stainless ILW package. The NDA
  evolution report discusses localized corrosion and chloride sensitivity.
  [Container designs](https://www.gov.uk/guidance/application-of-waste-package-specifications-for-low-heat-generating-waste-standardised-waste-container-designs) · [NDA DSSC/451/01](https://assets.publishing.service.gov.uk/media/5a81e778ed915d74e3400adf/NDA_Report_no_DSSC-451-01_-_Geological_Disposal_-_Waste_Package_Evolution_Status_Report.pdf)
- Experimental and modeling studies examine local ILW shell deformation
  caused by expansion of corrosion products within grouted contents.
  [Finite element study](https://www.sciencedirect.com/science/article/abs/pii/S0141029616308148) · [Grouted drum simulant experiments](https://www.sciencedirect.com/science/article/abs/pii/S0022311518303155)
- The Canadian Conservation Institute documents compact dark red-brown rust,
  active orange corrosion and pitting. Downward taper and branching are
  visual approximations of gravity-driven runoff from a wet source.
  [Canadian Conservation Institute](https://www.canada.ca/en/conservation-institute/services/preventive-conservation/guidelines-collections/metal-objects.html)
