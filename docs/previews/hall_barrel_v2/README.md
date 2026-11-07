# Reviewed LLW barrels in the actual 28-drum hall

These are native Isaac Sim 6.2 static camera captures, not generated concept images.
The fixed 28-drum layout, category split, colours, stable IDs and warning plates
were checked against the original seed-42 inventory. See the
[implementation and reproduction guide](../../hall_barrel_v2.md).

- `hall_overview.png`: the unchanged hall arrangement with the new painted-barrel surfaces.
- `A03_normal_rusted.png`: nominal body with thin chipped oxide.
- `B01_bulged_clean.png`: swollen body/domed lid without external rust.
- `C02_bulged_rusted.png`: the same deformation plus independent oxide; original grey palette preserved.
- `C02_lid_detail.png`: close view of the dome and lifted bungs.

Full native checks, camera poses and source fingerprints are in
`docs/validation/hall_barrel_v2.json`. Actual YOLO/Cosmos static-review outputs
are in `docs/validation/hall_barrel_v2_cosmos.json`. The initial unconstrained
Cosmos review made unsupported causal claims; the final review uses a constrained
observation/action schema and records only a proposed follow-up, never an executed
robot action or a confirmed gas/pressure diagnosis.

No full robot mission was run for these captures. The render workers stopped
after saving the screenshots. The existing detector weights were not retrained.
