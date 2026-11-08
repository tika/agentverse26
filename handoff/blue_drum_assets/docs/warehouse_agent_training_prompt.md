# Task for the teammate's agent

Build and validate a warehouse-domain YOLO26s detector for visible drums, corrosion and bulging. Work incrementally on this computer. Verify the assets, generate and inspect a small labeled pilot, then expand and train. Use your judgment on the renderer, annotation tooling, dataset size and training budget. Record deviations and their rationale. Stop at a failed gate and fix the underlying issue before scaling.

## What is already available

- Open `warehouse-v3/CANIS_YOLO_FOUR_CONDITION.usda` in Isaac Sim 6.2. Keep the extracted tree intact. The overlay references the 420-package warehouse and its textures using relative paths.
- Read `warehouse-v3/sample_catalog.json`. It identifies 24 controlled packages: six normal, six bulge-only, six corrosion-only and six with both. Every group includes LLW and ILW, one sample in each tier for each category, varied rack positions and varied severity for active defects. Other packages in this controlled scene are visual clean controls. The catalog records simulated design intent and helps find samples. It is not pixel-level annotation or evidence that a defect is visible from a given camera.
- The existing `barrels_v2_1200` release contains 1,200 labeled 640×640 painted LLW studio images. See `docs/warehouse_yolo_handoff.md` for the download command and baseline. The warehouse pack contains no new rendered dataset or trained checkpoint. The existing model is trained on LLW; measure ILW separately.

## 1. Render and label a pilot

1. Confirm the stage opens, textures resolve, and the catalog package prims exist. Record software versions, GPU, source revision and scene seed. Use the catalog aisle positions for initial camera targets, with sufficient standoff and tilt to see the relevant tier. Capture a frontal and oblique view of each of the 24 examples as an initial target of 48 raw frames. Include both tight and contextual views, varied distance and lighting, visible neighbors and some partial occlusion. Keep appearance and camera variation independent of condition. Reject clipped-through geometry, black or stale frames, and views that fail to show their intended inspection region.
2. Use class IDs `0 drum, 1 corrosion, 2 bulge`. Write standard YOLO boxes `class x_center y_center width height` normalized to the actual image dimensions. Label all visible drums, including clean controls. Label only visible corrosion and deformation. Both conditions can have separate boxes on the same drum. Draw the bulge box around the visible deformation region; document a consistent protocol for boundary cases and check it against the baseline label convention before mixing datasets. Avoid treating ordinary hoops, shadows, worn paint or an occluded fault as a positive. A normal drum has a drum box and no defect boxes.
3. Use tight visible instance boxes for drums. For corrosion, project a visible rust mask with depth/occlusion checks or manually annotate the RGB. The corrosion lives in the material texture and will not appear as a separate object in standard instance segmentation. For bulging use reviewed silhouette/depth cues and manual verification. Do not turn the catalog severity or a whole drum box into a defect label. Keep raw RGB and rendered review overlays in separate folders.
4. Validate image/label pairing, legal classes, positive box dimensions, normalized bounds, uniqueness and visible support. Build a review contact sheet covering every condition, category and tier. Count labels by class, condition and category. Record rejects and why. Fix annotation and camera issues before generating more data.

## 2. Build an independent training and evaluation set

- Use the controlled scene as a camera and annotation pilot. Its 48 views do not constitute 48 independent scenes. Generate additional sessions with disjoint seeds using the packaged generator and diversify lighting, rust severity/pattern, bulge size and orientation, package pose, distance, tier and occlusion where supported. Keep views from a scene and repeated package appearance together. Split by independent generation seed before capture or assignment. Do not randomly split frames from one scene across training and test.
- Start with a balanced pilot across the four condition groups and both materials. Increase volume only after the audit passes. Retain clean negatives and realistic confusing examples. If combining the studio data with new warehouse data, preserve the original studio split and class order, document mixture proportions, and keep a warehouse-only held-out test. Include difficult scenes and report limits if an upper tier is unreachable.
- Produce a portable dataset root with `images/{train,val,test}`, `labels/{train,val,test}`, `data.yaml` and a manifest of scene seeds, camera parameters, condition counts, image hashes and generator revision. Review random samples from every split before training.

## 3. Train, evaluate and deliver

- Install a compatible CUDA PyTorch and Ultralytics environment. Run a one-epoch smoke on the audited dataset to confirm class names, GPU and label loading. Record versions and the actual configuration. For a single GPU, start from an authorized YOLO26s checkpoint and adapt batch size to memory. A baseline command is:

  ```sh
  yolo detect train model=yolo26s.pt data=/absolute/path/to/data.yaml \
    imgsz=640 epochs=40 batch=8 device=0 seed=42
  ```

- Choose confidence thresholds using validation only. Freeze thresholds before evaluating the held-out warehouse split. Report mAP50 and mAP50–95 by class, precision and recall, plus package-level false positives and missed conditions. Break out LLW versus ILW and tiers, with sample counts. Include errors on clean drums and both-defect drums. Compare against the existing detector on the same held-out inputs if checkpoint access is available. Provide overlay examples with successes and failures.
- Deliver dataset and split manifests, an exact training command and environment, best checkpoint with SHA-256, evaluation JSON, and a short summary of remaining gaps. Share large data and checkpoints through the team-approved storage location and share the pointer with the warehouse team. Keep credentials and private evaluator truth out of model inputs and published inference artifacts.
