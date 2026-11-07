# Barrel detector pilot

The isolated pilot renders 40 images: eight independent Modal L40S containers,
five 640×640 views each. This is asset/annotation validation, not a trained model
or the final 1,500-image dataset. The existing hall, inventory, canonical spill
classes and scene snapshots are not modified.

```sh
python3 detector/modal_pilot.py
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

Annotation mapping is `0 drum`, `1 corrosion`, `2 bulge`. Corrosion geometry
uses the reviewed 0.35 mm v2 oxide overlay; adjacent occupied cells are grouped
into clusters bounded by 22.5° angular sectors. Native Replicator tight boxes
provide visible cluster extents. Sub-2-pixel boxes are ignored and counted.
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
claim should be extrapolated from five simultaneous render products per worker:
the final generator should reuse a camera and benchmark sustained capture.
