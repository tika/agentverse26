# CANIS dark-blue LLW drum assets

Extract the archive and open `blue_drum_studio.usda` in Isaac Sim. Keep
`assets/generated` beside the stage. Use the perspective viewport to frame
all four drums. The inherited review cameras frame individual examples.

| USD prim | Condition |
| --- | --- |
| /World/NormalClean | Clean, nominal shape |
| /World/NormalRusted | Corrosion only |
| /World/BulgedClean | Bulge only |
| /World/BulgedRusted | Bulge and corrosion |

The scene uses the painted LLW geometry from the earlier v2 studio study and
the simulator's existing dark-blue palette (RGB 38, 67, 91). Corrosion is
separate conforming geometry with an opacity map. The normal pair shares
the same underlying geometry and warning plate.

For varied labeled captures, apply `blue_studio_generator.patch` from the root
of a separate copy of the original studio generator checkout. It switches the
pilot to the blue palette while preserving its seeded camera, geometry,
corrosion and annotation logic. Use new scene seeds and keep each scene in
one split. YOLO class IDs remain 0 drum, 1 corrosion and 2 bulge.

This package contains source assets and a generator patch. Run the existing
Isaac Sim capture and annotation pipeline to produce labeled RGB frames.
