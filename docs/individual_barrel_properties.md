# Individual barrel properties

All 28 inventory entries now have a seeded `simulation_properties` profile in
`sim/drums.json`. Rebuild with the existing `load_layout()` entry point;
`make_inventory()` and `set_drum_faults()` regenerate the same profiles.

- Radiation strength and normal surface temperature vary by barrel within its category.
- Bulged drums have 7.5–8.5% swelling, 65–75 mm lid rise and 11–15 C peak heating.
- Only leaking fixtures emit external gas. Bulging without leakage does not create a plume.
- Leaking fixtures have positive contamination samples; clean controls stay below the demo limits.
- Existing rust, labels, paint styles and the 28 positions are preserved.
- The thermal renderer uses each profile; gamma/gas/swab/audio backends use the same profiles.
- The robot receives RGB/depth, thermal observations and ambient scalar measurements.
  Its memory stores nearby gamma/gas readings with an explicit mixed-source caveat.
  The complete simulator profile is never sent to YOLO or Cosmos.
- Internal pressure is not measured or invented. Bulge plus heat remains suspected pressure.

`docs/validation/drum_properties_28.csv` lists the fixtures for review; it is
simulator truth, not robot input. Zero gas values on sealed drums are intentional.
All values are hackathon fixtures, not validated operational or material limits.
