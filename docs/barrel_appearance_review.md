# Barrel appearance and two-cue screening study

This is an isolated design review, not a replacement of the full-hall dataset.
The source photograph collage is used as a visual reference; no stock image or
watermark is copied into the procedural textures. The supplied research notes
are context, not verified site data or an instruction to reproduce a particular
facility's condition.

Run `python3 tools/run_barrel_preview.py` on Modal or, locally:

```sh
/path/to/isaac-sim/python.sh sim/render_barrel_preview.py --allow-root
```

The render compares three versions of the same painted LLW barrel: nominal rusted,
bulged clean and bulged rusted. The two rusted variants use the same seeded
thin surface-corrosion pattern. Bulging and rust are independent switches. Paint wear is
grey, oxidation is a separate conforming mesh, the fresh oxide is restricted to
small edges, and damage concentrates at the chimes and rolling-hoop ridges.
The old large raised orange strips are not used. No liquid spill is included.
All new files remain in the `agentverse26` repository.

The proposed bulge uses a smooth 8% local radial expansion field (peak in the
middle of the body) and a 70 mm lid rise relative to the recessed nominal lid.
The largest diameter increase is not exactly 8% because the nominal chimes are
already wider than the cylindrical shell. The metadata records the deformation
parameter, not an assertion that a camera measured that parameter.
This is kinematic geometry, not pressure-vessel, gas, corrosion or rupture physics.
Gas is one possible reason for pressure; neither the render nor these cues
identify it. The full hall remains on its reviewed previous appearance until
this isolated design is accepted.

## Simplified deterministic filter

`sim/pressure_screen.py` accepts observed diameter change, observed lid rise,
recent **drum-surface** temperature readings and an ambient reference. It takes
a median of up to five surface readings and applies simulation thresholds from
`sim/inspection_config.json`:

```text
shape = diameter increase >= 2% OR lid rise >= 20 mm
heat  = median surface temperature >= ambient + 5 °C
shape AND heat -> suspected_pressurisation -> stop_and_alert
shape only    -> shape_anomaly            -> structural inspection
heat only     -> thermal_anomaly          -> thermal inspection
neither       -> no_two_cue_anomaly       -> continue monitoring
missing/invalid data -> hold_and_remeasure
```

These are illustrative hackathon thresholds, not real drum safety limits.
Every output has `gas_confirmed=false`. Cool bulges still prompt structural
inspection; the AND gate never suppresses that independent warning. A median
rejects an isolated outlier; it is not a calibrated thermal model or guarantee
against sensor failure. The caller must also enforce timestamps, valid range,
confidence and the project's sensor-dropout rules.

Example with ambient 18 °C: no deformation + surface 20 °C gives no two-cue
anomaly; deformation + surface 20 °C gives a shape warning; no deformation +
surface 30 °C gives a thermal warning; deformation + surface 30 °C gives suspected
pressurisation. These temperatures are synthetic example readings, not inferred
from RGB or calculated from gas chemistry. The function is tested independently;
it is not yet wired to a moving robot's depth/thermal estimators.

For a real sensor, use radiometric thermal-camera measurements or a contact
probe. The hall's ambient thermometer does not read the drum. Reflective metal
requires emissivity/reflected-temperature correction; see [FLIR's guidance](https://www.flir.com/en-gb/discover/professional-tools/how-does-emissivity-affect-thermal-imaging/).
A gas-specific measurement would be needed to identify a gas; this screening
module does not simulate one.

Sample tags are **A03** (nominal rusted), **B01** (bulged clean), **C02** (bulged rusted). These review tags do not rename any Dxx package in the hall inventory.

The [rendered three-variant comparison](previews/barrel_v2/README.md) is now
checked in. B01/C02 share a maximum-diameter increase of approximately 5.37%
and a 70 mm lid dome. The larger dome is an illustrative review choice, not a
validated physical prediction. The viewport reference grid is explicitly hidden
in captures (see the [upstream rendering issue](https://github.com/isaac-sim/IsaacSim/issues/887)).

Plates use the repository’s existing `plate_texture()` / `create_plate()` functions: yellow warning plate, trefoil, LLW, A03/B01/C02, WASTE PACKAGE and barcode. Internal identities remain D03/D05/D10. Preview copies face the review camera; the hall’s row-based plate orientation remains unchanged.

## Four GPUs for rendering

Use four independent one-GPU render workers:

```sh
python3 tools/run_barrel_parallel.py
```

This distributes the five camera views across four Modal workers. Each worker
owns an independent Isaac instance with one RTX GPU. Results are merged into
`sim/out/barrel_preview/`. The combined report includes each worker's actual GPU
and render-active count, subprocess duration and overall parallel wall time.
All four workers terminate after results download. Queue/startup/shader time can
still dominate a tiny preview; this is not a fourfold-speedup claim.

A shared four-L40S Isaac renderer was also tested: all four devices were Active,
but the rendered image omitted two barrel paint surfaces. That output was
**rejected**, despite the successful process exit and GPU activation. The exact
cause is unresolved in this Modal/image/scene combination. Prefer independent
workers for this preview. The runner now checks known yellow-body regions to
reject missing-surface output before accepting a preview.

The lower-level experimental host mode remains available through
`ISAAC_RENDER_GPU_COUNT=4 python3 tools/run_barrel_preview.py`, but it currently
fails that visual acceptance check for this fixture. Existing team entry points
still default to one GPU. See [NVIDIA's multi-camera performance notes](https://docs.isaacsim.omniverse.nvidia.com/latest/reference_material/benchmarks.html)
and [Modal's multi-GPU support](https://modal.com/docs/guide/gpu).
