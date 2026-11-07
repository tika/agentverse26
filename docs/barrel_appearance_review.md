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

The render compares two versions of the same painted LLW barrel: nominal and
bulged. Both use the same seeded thin surface-corrosion pattern. Paint wear is
grey, oxidation is a separate conforming mesh, the fresh oxide is restricted to
small edges, and damage concentrates at the chimes and rolling-hoop ridges.
The old large raised orange strips are not used. No liquid spill is included.
All new files remain in the `agentverse26` repository.

The proposed bulge uses a smooth 4% local radial expansion field (peak in the
middle of the body) and a 40 mm lid rise relative to the recessed nominal lid.
The largest diameter increase is not exactly 4% because the nominal chimes are
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
