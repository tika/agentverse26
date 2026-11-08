# Agentverse warehouse · Environment v2

Open [warehouse-v3.usda](warehouse-v3.usda) in Isaac Sim using **File → Open**. Keep the USD sublayers and `assets/` beside it. Open [warehouse-overhead.usda](warehouse-overhead.usda) for the roof-off review. The 24 × 28.30 m warehouse uses metres and Z-up. The robot spawn, route graph and per-drum inspection aisle are in [map.json](map.json). The scene provides the spawn transform at `/World/RobotSpawn`; load the existing Spot separately for a robot session.

The five aisles between rack rows have 3.32 m of clear width.

For autonomous runs, use the [randomized defect session launcher](DEFECTS.md).

## Rebuild and check

From this directory, use Python 3.11+ with `usd-core`, `numpy` and `Pillow` installed. The shared workspace already has these in `.venv-usd`. The drum print uses Arial Bold when available on macOS, or Pillow's bundled font. Set `WAREHOUSE_PRINT_FONT` to choose a font file explicitly.

```sh
USD_PYTHON=.venv-usd/bin/python
"$USD_PYTHON" layout.py
"$USD_PYTHON" build_shell.py --map map.json --out shell.usda
"$USD_PYTHON" build_v3.py
"$USD_PYTHON" verify_stage.py > checks/environment-v2-codex-storage.json
"$USD_PYTHON" checks_v3.py --stage warehouse-v3.usda --map map.json --out checks/environment-v2-stage.json
```

## Isaac RTX review

The Modal launcher snapshots the composed USD, map and textures, then opens the actual stage entry point in headless Isaac Sim 6.2 on an RTX PRO 6000. Install Modal in the client environment and authenticate it before running. Use the Python executable from your authenticated Modal environment.

```sh
ISAAC_MODAL_PYTHON=python
"$ISAAC_MODAL_PYTHON" -m modal run modal_isaac_check.py --output review/isaac-env2-verified --tour
ffmpeg -framerate 24 -i review/isaac-env2-verified/tour_frames/f%04d.jpg -c:v libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart review/warehouse-environment-v2-rtx-tour.mp4
```

The report records the GPU, exact Isaac version, USD input hashes, semantic-label application, physics probes and captures. Stage checks measure static clearance for a 0.40 m radius and 1.10 m height envelope. The inspection captures use the Spot inspection camera's height, forward offset, pitch and optics at stationary route positions. They are visual legibility checks. No detector or live Spot route traversal was part of this review.

The shutter curtains are closed and collidable. The floor and storage use static collision, with one storage proxy per rack. The 420 print panels are UV-mapped into the existing drum bodies. Isaac applies the `class`, `drum_id` and `waste_category` labels at runtime.
