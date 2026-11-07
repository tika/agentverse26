# Isolated barrel v2 review

Left to right: **A03 nominal rusted**, **B01 bulged clean**, **C02 bulged rusted**.
Bulged variants use the same deformation: 8% peak local radial scaling field
(approximately 5.37% increase in maximum diameter) and 70 mm lid rise from the
nominal recessed lid. This is a visibly amplified demonstration, not gas physics.

![Three variants](normal_vs_bulged.png)

![Bulged without rust](bulged_clean.png)

![Bulged with rust](bulged_rusted.png)

Actual Isaac renders; no generated-image or image-editing model was used.
The main 28-drum hall's fault appearance was not replaced by this study.
See [review notes and pressure-screen logic](../../barrel_appearance_review.md).
Run `python3 tools/run_barrel_preview.py` to rebuild and capture.

The plates are the actual shared repository design: yellow warning background, trefoil, LLW category, row/zero-padded-slot ID, WASTE PACKAGE and barcode. Internal IDs are D03, D05 and D10 respectively.

The current preview was rendered by four independent L40S GPU workers in
178.6 s wall time including setup and collection. Each worker's renderer had
one active GPU, and the physical GPU UUIDs were distinct. All three painted
body regions passed the fixture-specific validation. The shared four-GPU
renderer experiment was rejected for missing surfaces; it is not used here.
Run `python3 tools/run_barrel_parallel.py` to reproduce this render mode.
