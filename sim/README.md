# Nuclear-store simulation — Steps 0–1, MVP v2

Work lives in the `agentverse26` repository. Review each step using exported
screenshots/video, then explicitly continue to the next step. The empty hall
is built and checked. Barrels and faults have not been added yet.

## Version and launch

The clean NVIDIA container reports **6.2.0-rc.14+release.52805.02189a84.gl**.
The image is `nvcr.io/nvidia/isaac-sim:6.2.0`; Isaac lives at `/isaac-sim`.
The Mac submits standalone scripts through Modal to an RTX-capable GPU. The scripts
run headlessly; the GPU is stopped after output is downloaded.

From the repository root, with an authenticated Modal account:

```bash
python3 -m pip install -r tools/requirements.txt
python3 tools/check_modal_install.py
python3 tools/run_step0.py
```

The exact command executed inside the GPU container is:

```bash
/isaac-sim/python.sh /workspace/sim/hello_world.py --allow-root
```

`hello_world.py` is the ten-line entry point. `capture_step0.py` adds a fixed
camera, checks module imports and two semantic taxonomies, and requests one RGB
image through Replicator's BasicWriter. Outputs go to `sim/out/step0/` and are
ignored by Git. `cube.usda` is a small inspection artifact, not the future hall.

## Installed APIs

These names were inspected in this image's installed extension source. The
machine-readable inventory is `installation_report.json`.

| Purpose | API for this version |
| --- | --- |
| Application | `isaacsim.SimulationApp` |
| Stage and prim utilities | `isaacsim.core.experimental.utils.stage`: `get_current_stage`, `define_prim`, `delete_prim`, `set_stage_units`, `set_stage_up_axis` |
| Scene geometry | `pxr.UsdGeom`, `pxr.UsdLux`, `pxr.Gf` |
| Semantic labels | `isaacsim.core.experimental.utils.semantics.add_labels(prim, labels=[...], taxonomy='class')` |
| A second semantic taxonomy | The same function with `taxonomy='drum_id'` |
| Replicator | `omni.replicator.core` (installed extension version 1.13.38) |
| Writers and annotators | `rep.WriterRegistry`, `rep.AnnotatorRegistry`; the cube check uses `BasicWriter` with `rgb=True` |
| Camera used by the check | `pxr.UsdGeom.Camera`, connected to a Replicator render product |
| Installed camera wrapper | `isaacsim.sensors.camera.Camera` lives in the deprecated extension tree; its presence does not make it the preferred API for new scene code |
| Built-in robot specifications | `isaacsim.robot.policy.examples.bundled.spot.get_spot_spec` and `...bundled.anymal.get_anymal_spec` |

The old `isaacsim.core.utils` modules are also present in `extsDeprecated`.
New semantics code will use the inspected `taxonomy` API, rather than mixing
that call signature with the compatibility module's `instance_name` argument.
Quadruped asset loading and walking policies are deferred to v2 Step 7.

## Validation boundary

**Step 0 passed:** a 640×480 PNG of the blue cube was downloaded and visually
checked. Both semantic taxonomies returned their expected labels, and the stage,
camera-wrapper and Spot/ANYmal specification modules imported successfully.
Replicator's BasicWriter produced the RGB image; the GPU session then stopped.

Reading source, importing modules, exporting USD and rendering pixels are separate
checks. Only a downloaded, visually inspected PNG establishes the Step 0 visual
check. See the run log and `runtime_checks.json` for the actual execution results.
No inventory, drum states or navigation files are generated in Step 0.

The cube uses metre units, Z up, a fixed camera and real-time RTX rendering.
There is no random scene generation in this check.

## Step 1: build and review the empty hall

From the repository root:

```bash
python3 tools/run_hall.py
```

This uses a regular Modal GPU job with an L4/L40S/A10G fallback list. The final
verified run used an L40S. It uploads the simulation source, runs the standalone
command below, downloads the scene, textures and four screenshots, then stops.

```bash
cd /workspace/sim
/isaac-sim/python.sh /workspace/sim/capture_hall.py --allow-root
```

To build without rendering review images, on a machine with Isaac installed:

```bash
/isaac-sim/python.sh sim/build_hall.py --allow-root --seed 42
```

Inside an already-running Isaac script, call `build_hall.build_scene(seed=42)`.
It rebuilds `/World/Hall`, `/World/Drums`, `/World/Defects` and
`/World/Obstructions`. The latter three stay empty in Step 1. The hall is in
metres with Z up and its front-left interior floor corner at (0, 0, 0).

The concrete, roller shutter, signs, stencils and drain grates are procedural.
The floor has rectangular repairs, dry scuffs and wheel marks; there are no
decorative liquid stains or tide marks. Wall formwork is approximately 2.4 ×
1.2 m, with a washable lower 1.5 m coating. Thirty-two detail meshes cover doors,
crane, duct, cable trays, monitors, CCTV, signs, fire point and two drain grates.
Eight high-bay lights and their housings are separate from that detail count.

Files and their roles:

| File | Role |
| --- | --- |
| `build_hall.py` | Assemble the hall and its fixed lighting |
| `textures.py` | Generate and cache the small texture bank from one seed |
| `materials.py` | Create UsdPreviewSurface materials with relative image paths |
| `geometry.py` | Build UV-mapped boxes, cylinders and sign quads |
| `aisles.py`, `aisles.json` | Store the fixed clear corridors and connected waypoint graph |
| `capture_hall.py` | Check rebuilding, UVs and labels; capture four camera angles in one pass |
| `hall.usda` | Saved Step 1 scene, including review cameras |

Open `sim/out/step1/front_overview/rgb_0000.png`, `rear_overview/rgb_0000.png`,
`entrance_detail/rgb_0000.png` and `aisle2/rgb_0000.png` to review the hall.
`sim/out/step1/report.json` records build times, checks and camera poses.
The floor/aisle graph has 54 waypoints and 57 undirected edges. Rectangle arrays
in `aisles.json` use `[xmin, ymin, xmax, ymax]`; graph edges are pairs of node IDs.

### Step 1 checks and practical limits

The same seed produced identical USD scene data on two builds. The first build
took about 3 seconds and the cached build under 1 second. All 48 meshes have
UVs; all 19 texture references are relative. There are no semantic classes on
the hall or its background details. Every saved review image is 1024 × 640.

Lights have stable names `/World/Hall/Lights/Row1_L01` through `Row2_L04`.
`Row2_L04` has 40% of the nominal light intensity. The camera uses fixed indoor
exposure (ISO 400, f/2.8, 1/60 s); automatic exposure is disabled. The low dome
fill has shadows disabled to approximate bounced light cheaply. Housings use a
simple emissive surface. This is a realtime MVP, with no path tracing or baked GI.
The controls follow NVIDIA's [render settings documentation](https://docs.omniverse.nvidia.com/kit/docs/omni_replicator/1.12.16/source/extensions/omni.replicator.core/docs/API.html).
The scripts apply this exposure profile; a USD viewer opened manually uses its
own exposure settings. Use the supplied capture command to reproduce these views.

Textures are at most 1024 px and cached in `assets/generated/`. To supply an
alternative later, put it in `assets/provided/<material>_<channel>.png`, such as
`floor_diffuseColor.png` or `wall_normal.png`; the builder prefers it over the
generated version. Delete a generated cache file to regenerate that component.
No external scene assets have been downloaded. Barrels, faults, robot, radiation
model, dataset generation and agent/dashboard integration remain later steps.
