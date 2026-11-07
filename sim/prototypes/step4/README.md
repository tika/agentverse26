# Levi's Step 4 semantic-box proof

This standalone Isaac Sim 6.0.1 prototype runs on Modal L40S. The shared
Isaac Sim 6.2 hall and Spot rollout keep their existing entry points.

From the repo root, with Modal authenticated and FFmpeg installed:

```sh
modal run sim/prototypes/step4/inspection_mvp.py --seed 42 --encoder ffmpeg
```

Artifacts go to the ignored `sim/out/levi_step4/` directory. It contains the
0.60 m camera-height fly-throughs, raw RGB, annotated PNG, pixel-coordinate box
JSON, scene USD and plate textures, drum inventory, and subprocess log.

The seed-42 proof showed separate tight boxes for the D10 body, three corrosion
patches, puddle, and leak trail. Clean drums also received boxes. Replicator
returned lowercase drum IDs, which the exporter normalizes to the uppercase
inventory IDs. Rebuilding the scene inventory with the same seed returned
identical JSON. [Verified Modal run](https://modal.com/apps/levi-stein-26/main/ap-xSXTvnQtA6X6p6yNm1MBgg).

`set_drum_state()` replaces an individual drum's visible defect meshes and
writes the inventory. The demo layout includes D10 (corrosion and leak) and D25
(corrosion and residue). The proof camera validates D10; it is a stationary
annotator check, separate from the team's onboard Spot capture. The proof uses
simple materials, and generates one boxed test frame per run.
