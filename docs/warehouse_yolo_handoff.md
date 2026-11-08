# Warehouse assets and YOLO training handoff

## Start here

Clone the team repository and check out `codex/warehouse-dog-inspection`. Use `git rev-parse HEAD` to record the exact revision used by each machine.

- **Warehouse scene:** Open `sim/warehouse-v3/warehouse-v3.usda` in Isaac Sim 6.2. Keep its sibling USD layers and the complete `assets/` directory in place. The authored map and the base scene cover 420 drums across three tiers and two waste categories.
- **Randomized drum assets:** With Isaac's Python, run the command below from the checkout root. This produces a reproducible scene with new rust textures and modified bulge meshes, plus an evaluator-only manifest. Keep the generated stage, textures and source checkout together. Regenerate on the destination machine because the session overlay references the local base stage by absolute path.
- **Training images and labels:** Download the existing verified `barrels_v2_1200` LLW release using a Modal profile with access to the detector team's volume. It contains 900 train, 150 validation and 150 test images. See the [release report](barrels_v2_1200_release.md) for provenance and the [generator handoff](dataset_generation_handoff.md) for rebuilding the studio dataset. Use the existing split for comparable baselines.
- **Class contract:** `0 drum, 1 corrosion, 2 bulge`. The legacy `sim/training_capture.py` maps class 2 to spill and is unsuitable for these labels. The randomized warehouse scene and manifest are assets for rendering and evaluation. The manifest is not a YOLO label file.

```sh
/path/to/isaac-sim/python.sh sim/warehouse-v3/drum_faults.py \
  --seed 42 --output out/warehouse-assets/seed-42/warehouse.usda \
  --manifest out/evaluator/seed-42.json

mkdir -p out/datasets
modal volume get detector-data /archives/barrels_v2_1200.zip out/datasets/barrels_v2_1200.zip
unzip -l out/datasets/barrels_v2_1200.zip | head -20
```

Extract the dataset, locate its `data.yaml`, and confirm the train/val/test image directories and paired labels. On a CUDA machine with PyTorch and Ultralytics installed, use the following single-GPU entry point. Set the batch for that machine and record all overrides. Use the [verified baseline recipe and evaluation handoff](yolo26s_training_serving.md) for a reproduction.

```sh
yolo detect train model=yolo26s.pt data=/absolute/path/to/data.yaml \
  imgsz=640 epochs=40 batch=8 device=0 seed=42
```

For new warehouse-domain training data, first render and annotate a small pilot covering both categories, all tiers, clean controls, corrosion, bulge and combined conditions. Annotate visible regions from RGB and matching render data. In particular, the warehouse corrosion is baked into the drum material, so instance segmentation alone will not yield corrosion boxes. Use a projected visible rust mask or reviewed manual annotations. Hold out whole scene seeds, keep raw RGB separate from review overlays, and audit ILW separately because the existing release is painted LLW only. Share the dataset manifest, model hash, and held-out metrics with the team.

## Current stage

Assets and reproducible scene recipe are checked in. The baseline LLW dataset already exists in the detector team's Modal volume. New warehouse-specific training images and annotations still need a pilot. The live dog camera gate remains open. The chase position used by the original walk is 2.4 m behind Spot, so at spawn x=1 m it can put the camera outside the hall. The still-camera pass recovered a readable ID but cropped Spot and the drum. Fix the moving chase geometry and verify full framing through the turn before connecting live YOLO and package memory.
