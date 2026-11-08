# Task for the training agent

Build and validate a blue LLW studio dataset compatible with the yellow
`barrels_v2_1200` release, then train and evaluate YOLO26s after the dataset
passes review. Record the code revision, environment, GPU, scene seeds,
capture settings, and any deviations.

## Verify and render a pilot

1. Open `blue_drum_studio.usda` in Isaac Sim 6.2. Confirm that all four
   catalog prims and texture maps resolve. Inspect a front and oblique view
   of each condition. Confirm that chipped oxide and lid/body deformation
   are visible in the intended views. The catalog records asset condition.
2. Apply `blue_studio_generator.patch` to a fresh copy of the studio
   generator on the detector-training branch. Follow
   `docs/dataset_generation_handoff.md` for runtime and capture commands.
   Run a small seeded capture before starting a full render. Include close
   and contextual views, partial occlusions, and varied lighting.
3. Use 640×640 RGB and normalized YOLO boxes with IDs 0 drum, 1 corrosion,
   and 2 bulge. Follow the studio baseline convention: label visible drums,
   visible corrosion patches, and one visible whole-drum box for a visibly
   bulged drum. Keep raw RGB separate from review overlays. Reject black
   frames, stale frames, bad camera intersections, and unsupported labels.
4. Check frame and label pairing, valid classes and normalized bounds,
   box support, duplicates, class counts, and representative overlays
   across conditions and viewpoints. Resolve any failures before scaling.

## Expand, split, and train

- Use independent blue scene seeds and keep every view of a scene in one
  split. Preserve the yellow release's split assignments. For a 1:1
  blue-to-yellow image mix, target 900/150/150 blue train/val/test images.
  Record actual counts and drum-instance ratios separately. Keep color,
  condition, and viewpoint variation independent.
- Deliver `images/{train,val,test}`, `labels/{train,val,test}`, `data.yaml`,
  metadata, and a manifest of seeds, camera settings, conditions, hashes,
  and generator revision. Inspect samples from all splits.
- Run a one-epoch YOLO26s smoke test, then use the settings in
  `docs/yolo26s_training_serving.md` as the starting point. Choose confidence
  thresholds on validation. Report held-out mAP50, mAP50–95, precision and
  recall by class and color, with counts and review overlays. Evaluate
  warehouse performance on a separately held-out warehouse set.
- Deliver the dataset and split manifests, command and environment,
  checkpoint with SHA-256, evaluation JSON, and remaining gaps. Use the
  approved team storage for large artifacts.
