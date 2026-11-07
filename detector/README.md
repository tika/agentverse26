# Barrel detector pilot

For the prepared **single-workspace 1,200-image / 10 RTX PRO 6000** run, start with
[the complete agent handoff](../docs/dataset_generation_handoff.md). It includes
the frozen plan, generation, GPU comparison, validation, recovery and publication
to the owner's Modal Volume. **The full 1,200-image run is now authorized;
training remains separate.** Check for an active run/release before starting
another. The following commands describe the earlier smaller pilot.

The default isolated pilot renders 40 images: eight independent Modal L40S containers,
five 640×640 views each. This is asset/annotation validation, not a trained model
or the final 1,500-image dataset. The existing hall, inventory, canonical spill
classes and scene snapshots are not modified.

```sh
python3 detector/modal_pilot.py
# Optional small smoke test, or a larger review (16 GPUs requires quota):
python3 detector/modal_pilot.py --seeds 1
python3 detector/modal_pilot.py --seeds 16 --frames-per-seed 10
# Use the run ID printed above; this does not allocate a GPU:
python3 detector/status.py RUN_ID
python3 -m unittest detector.test_pilot -v
```

Each seed has all four combinations of rust and bulge, including a normal clean
control. Printed A01–D07 IDs are sampled without replacement using a separate
RNG stream from the faults. They are metadata, not detector classes. Each drum
has its own rust seed and circumference shift. Bulged drums vary only within
7–9% peak local radial scaling and 65–75 mm lid rise above the recessed lid;
the reference remains 8% / 70 mm. These are not severity classes. All assets are
painted LLW barrels; ILW/stainless is outside this pilot.

## Diversity v2

Every five captures contain three **single-barrel** inspection views and two
**multi-barrel** context views. Single views explicitly hide every other drum
and its corrosion geometry. Export assertions require exactly the intended drum
in their native boxes; context views require at least two visible drums. Every
visible drum is annotated, including cropped/partly occluded ones. One image is
one training sample and can contain several object/condition annotations.

Camera azimuth covers front/right/back/left with jitter, single-view distance
is 1.0–1.5 m and context distance is 2.8–3.7 m. Camera height is 0.45–0.8 m,
with fixed 640×640 / 77.3° horizontal FOV calibration. The room uses independently
randomised row/staggered/cluster layouts, layout rotation, four neutral floor/wall
palettes, floor roughness, key/fill directions, area-light sizes, brightness and
3900–6900 K colour temperature. Frames also vary illumination strength. Background
crates provide distractors; the second context view has a low foreground crate
for partial occlusion. All switches are seeded and independent of defect state.
These variations are fixtures, not a claim to cover every real inspection scene.

One camera/render product is reused sequentially. Before every capture, pose,
visibility and lighting are changed, rendering is settled, then Replicator steps
with four RTX subframes. This replaces the v1 pilot's five simultaneous cameras.
The v1 timing report remains unchanged and is not a timing prediction for v2.

Annotation mapping is `0 drum`, `1 corrosion`, `2 bulge`. Corrosion geometry
uses the reviewed 0.35 mm v2 oxide overlay; adjacent occupied cells are grouped
into clusters bounded by 22.5° angular sectors. Native Replicator tight boxes
provide visible cluster extents. Nearby visible rust boxes are then merged **per
drum**, bounded to 55% of drum image width / 27% of image height and a limited
empty-space expansion. Distant patches and different drums cannot be combined;
pre-existing larger native clusters are retained rather than silently truncated.
Merging happens before filtering: corrosion boxes below 3 pixels in either
dimension are counted and dropped, other classes use 2 pixels. On the same 40 v1
images, this revised policy reduces corrosion labels from 1,970 to 773 (60.8%).
The rendered oxide itself is unchanged; no opaque paint/proxy geometry is added.
Bulge is one whole-visible-drum condition box, derived from that drum's native
box and authored condition. It overlaps the drum box; no invisible proxy mesh
is rendered. No gas or pressure measurement is claimed.

Results are saved to `out/detector_pilot/RUN_ID/` and persisted in the
`detector-data` Modal Volume under `/pilots/RUN_ID/seed_XX/`. Each worker saves
native RGB and boxes, YOLO labels, annotated previews, metadata, progress, logs
and timings. `timing.json` distinguishes total launcher wall time from worker
time and batch dispatch/download time. The image build and scheduling overhead
are included in launcher wall time. `contact_sheet.jpg` shows all 40 frames.
The temporary `studio.usda` is a texture-resolution anchor, not a saved scene
deliverable; use the seeded Python builder to reproduce the scene.

```sh
python3 detector/package_pilot.py out/detector_pilot/RUN_ID
```

This creates `dataset/images/`, `dataset/labels/` and `dataset/metadata/` with
matching `seed_XX_frame_XXX` names and a SHA-256 manifest. No train/validation/test
split is assigned to this inspected pilot. The final release must hold out scene
and rust seeds before generation. Raw data and model weights stay outside Git.

Workers commit completed results to distinct Volume paths, so other workers
cannot overwrite them. A rerun uses a new run ID. No unmeasured bulk-throughput
claim should be extrapolated from the v1 five-simultaneous-product pilot.
The v2 generator reuses one camera; benchmark its sustained capture separately.
