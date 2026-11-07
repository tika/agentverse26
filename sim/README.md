# Nuclear-store simulation — Step 0

Work lives in the `agentverse26` repository. Review each step using exported
screenshots/video, then explicitly continue to the next step. The hall and drums
have not been built yet.

## Version and launch

The clean NVIDIA container reports **6.2.0-rc.14+release.52805.02189a84.gl**.
The image is `nvcr.io/nvidia/isaac-sim:6.2.0`; Isaac lives at `/isaac-sim`.
The Mac submits standalone scripts through Modal to an L40S GPU. The scripts
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
Quadruped asset loading and walking policies are deferred to Step 5.

## Validation boundary

**Step 0 passed:** a 640×480 PNG of the blue cube was downloaded and visually
checked. Both semantic taxonomies returned their expected labels, and the stage,
camera-wrapper and Spot/ANYmal specification modules imported successfully.
Replicator's BasicWriter produced the RGB image; the GPU session then stopped.

Reading source, importing modules, exporting USD and rendering pixels are separate
checks. Only a downloaded, visually inspected PNG establishes the Step 0 visual
check. See the run log and `runtime_checks.json` for the actual execution results.
No hall, inventory, drum states or navigation files are generated in Step 0.

The cube uses metre units, Z up, a fixed camera and real-time RTX rendering.
There is no random scene generation in this check.
