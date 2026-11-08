# Environment v2 validation

2026-11-08 · Codex

## Composed stage

- The 24 × 20 m stage resolves all four layers and 429 texture assets with no unresolved dependencies. The roof-off entry point hides `/World/Hall/Roof`.
- All 420 canonical drum paths, world transforms, zone and location metadata, and body geometry match the starting inventory. There are 336 LLW drums and 84 ILW drums. The existing shapes and sizes are preserved. The 140 storage columns are three high and the deepest banks are two rows. Every drum has an aisle-facing print material. The plate geometry was removed.
- The robot spawn is (1, 6, 0). Route geometry matches the starting map. Minimum static route centerline clearance is 0.53 m against a 0.40 m radius envelope.
- The roof is pitched at 5°. The deck underside is at 9.08 m at the eave and the deck top is 9.995 m at the ridge. Trusses bear on column caps and 275 mm Z-purlins sit between the top chords and deck. The highest checked framing vertex is 0.8 mm below the deck underside. The trolley clears the truss bottom by 160 mm and the fixture housings by 140 mm.
- The east end remains a closed ILW service opening, 4.0 × 4.5 m. The curtain collider spans the clear opening. Guides, head box and threshold align with the opening. The west gate uses the same closed construction.
- The full-slab concrete maps add saw-cut joints, low-contrast variation and aisle wear. The slab mesh, transform and enabled collider match the baseline. Paint markings are separate from the slab surface.
- The shell builder reproduced identical USD bytes across two builds. The storage, site, both entry layers, drum textures and map also matched a fresh rebuild.

Exact starting hashes are in `checks/environment-v2-start.sha256`. The final launch snapshot hashes are in `review/isaac-env2-verified/snapshot_sha256.json`. See [README.md](README.md) for the build and launch commands.

## Isaac RTX and tour

- Isaac Sim `6.2.0-rc.14+release.52805.02189a84.gl` opened the final input snapshot on an NVIDIA RTX PRO 6000. All 79 physics probes passed, and Isaac applied the baseline `class`, `drum_id` and `waste_category` assignments to all 420 drums.
- Reviewed roof framing from the aisle and a high section camera. The trusses and purlins read separately below the roof sheets. The rear elevation and approach show the shutter's horizontal slats and head box. The floor review shows the joints and readable yellow markings.
- Read the trefoil, location code and canonical ID on the first-tier LLW sample `B-L-01-T1 / D09` and ILW sample `B-R-11-T1 / D20` in the two 640 × 640 Spot-geometry captures. The stationary review camera used the source rig's 0.60 m height, 0.48 m forward offset, 10° down pitch and 78° field of view, with the corresponding body position on the mapped route.
- This was visual review of two first-tier samples. Upper-tier coverage, detector accuracy and live Spot traversal were outside the checks run.
- The 1280 × 720 H.264 tour decoded through all 720 frames at 24 fps, with a 30.00-second duration. It includes the roof-off overview, aisle-level roof, LLW and ILW close passes, and the rear wall approach.

[Final Isaac RTX run](https://modal.com/apps/levi-stein-26/main/ap-Hvm4OypKz70v2kIZ2jmrWE)
