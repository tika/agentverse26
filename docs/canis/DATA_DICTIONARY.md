# C.A.N.I.S. per-drum data dictionary

This dictionary covers every per-drum field in the 420-drum warehouse, read from the code at `a42b8eb`
(`levi/warehouse-randomized-defects`). It has three layers:

1. **Known inventory.** Public. The console loads it from `sim/warehouse-v3/map.json`.
2. **Robot observations and interpretations.** Public when an observation source supplies them. They travel as `canis.v1` messages.
3. **Private simulator and evaluator truth.** Never sent to the console, the agent, fixtures, logs or the build.

Column meanings:

- **Visibility** says who may see a field: *public*, *observation* (only after a sensor or robot produced it), *derived* (computed by the console from observations), or *private* (simulator/evaluator only).
- **Freshness** gives the default staleness window. Windows are in `canis/src/ingest/freshness.ts` and are measured on the source clock (`t_sim_s`) when the message has one.
- **Missing** says how the console behaves when the field is absent.

The console enforces the layer-3 boundary in code:

- `canis/src/contracts/private-keys.json` lists the private keys.
- `FeedBus.ingest()` rejects any inbound payload containing one of them at any depth, and logs only the key paths.
- `npm run check:privacy` scans `public/`, `src/fixtures/` and `dist/`.

---

## Layer 1 — Known inventory (public)

**Source.** `sim/warehouse-v3/map.json` (`schema_version` 1, metres, Z up, `baseline_revision` `50abf76`). Map positions come from `layout.py`, and the print text from `storage.py:print_texture()`.

**How the console gets it.** `canis/scripts/build-public-map.mjs` copies an allowlist of fields to `canis/public/data/warehouse-map.public.json` and records the source sha256. Field names below are the public names, with the `map.json` key in brackets where it differs.

**Freshness.** Static for a build. The sha256 shown in the footer identifies the map revision.

| Public key [map.json key] | Unit / type | Meaning | Visibility | Missing behaviour |
|---|---|---|---|---|
| `id` [`id`] | string `D01`…`D420` | Canonical drum ID, also printed as `"{category}  /  {id}"` on the drum panel and used as the USD prim name | public | Required; build fails without it |
| `location_code` [`display_id` = `location.location_code`] | string `A-L-01-T1`, depth-2 slots add `-D2` | **Printed location code.** This is the observation key shared with the mission ledger (`scripts/hot/warehouse_observations.py`, `warehouse_routes.inspection_targets()`). Unique across all 420 | public | Required |
| `category` [`category`] | `LLW` \| `ILW` | Waste class: 336 LLW, 84 ILW | public | Required |
| `zone` [`zone`] | `A` \| `B` | Storage zone (`zones`: A = LLW, B = ILW) | public | Required |
| `row` [`row`] | string `A-L` | Rack row (lane + side) | public | — |
| `stack_id` [`stack_id` = `location.stack_id`] | string `A-L-P01` | Rack / pallet stack ID; matches `racks[].id`. One rack holds several XY positions | public | — |
| `lane`, `side`, `column` [`location.*`] | string, string, int | Lane letter, side (L/R) and column index in the location code | public | — |
| `tier`, `tier_count` [`location.tier`, `location.tier_count`] | int 1–3 | Tier (T1 = floor pallet). Three drums share each XY position (140 stacks × 3 tiers); the UI asks for the tier explicitly | public | — |
| `depth` [`location.depth`] | int 1–2 | Row position from the aisle (252 at depth 1, 168 at depth 2) | public | — |
| `x_m`, `y_m` [`x`, `y`] | m, world frame | Drum axis position | public | — |
| `base_z_m` [`base_z` = `location.base_z_m`] | m | Drum base height, equal to the tier deck top | public | — |
| `yaw_rad` [`yaw`] | rad | Drum yaw about Z | public | — |
| `radius_m`, `height_m` [`radius`, `height`] | m | Nominal dimensions: LLW 0.299 × 0.88 (208 L), ILW 0.40 × 1.20 (500 L) | public | — |
| `face_sign` [`face_sign`] | ±1 | Which side (±Y) the printed panel faces | public | — |
| `facing_aisle` [`facing_aisle`] | int 1–3 | Inspection aisle index | public | — |
| `inspection_route_y_m` [`inspection_route_y`] | m | Y of the route line used to inspect the drum. `warehouse_routes.py` stops at `(x, inspection_route_y)` | public | — |
| `prim_path` [`prim_path`] | USD path `/World/Drums/D01` | Prim carrying the Isaac `class`, `drum_id` and `waste_category` labels | public (display only) | — |

Map-level public fields: `hall_m` (24 × 28.30 × 10.36 m), `robot_start_m` (1, 6, 0; also `/World/RobotSpawn`), `zones`, `staging_bounds_m`, `racks[]` (`id, zone, category, center, size 1.34 m, deck_tops`), and `nodes` / `edges`. The route graph has lines at y = 1.3, 4.83, 9.49, 14.15, 18.81, 23.47 and 27.0. The five inner lines (4.83 … 23.47) are the 3.32 m clear aisles between rack rows.

### `map.json` fields the console deliberately drops

The map-level `seed` and `v2_node_positions_in_v3` are not copied. The per-drum fields below are dropped too:

| map.json key | Why it is not public |
|---|---|
| `state` (`"clean"` for all 420), `faults`, `defects`, `corrosion_severity`, `shape {max_radius, lid_rise, dents}`, `internal_corrosion`, `obstructed` | Baseline placeholders written before session faults are generated. They are never updated per session. Showing `state: clean` would assert a diagnosis the robot has not made. |
| `source_strength` (1 LLW / 20 ILW) | Legacy class-proportional source proxy; not an observation |
| `scene_seed`, `appearance_seed`, map `seed` | Generator seeds |
| `paint_color`, `visible_face` | Render inputs, not inspection data |
| `legacy_id`, `legacy_display_id`, `legacy_x`, `legacy_y`, `v2_xyz` | v2 → v3 migration bookkeeping |

The older **28-drum demo** (`sim/drums.json`, `SensorWorld`, `sim/inspection_payloads.py`) is a separate map and sensor contract. The console does not read it.

---

## Layer 2 — Robot observations and interpretations

Observations only reach the console as `canis.v1` messages (`canis/src/contracts/messages.ts`). Interpretations are separate record types that point back to observations through `evidence: [{kind, ref}]`.

### 2a. Scalar readings — `sensor_reading`

**Source.** `WarehouseSensors.sample(position, time_s, gamma_xyz=, gas_xyz=)` in `sim/warehouse-v3/warehouse_sensors.py`. It runs simulator-side; only its return value crosses the boundary.

**Freshness.** 8 s (`FRESHNESS_S.sensor`; the gamma integration is 2 s).

| Key | Unit | Meaning | Visibility | Missing / special values |
|---|---|---|---|---|
| `time_s` | s (sim) | Sample time; must be monotonic | observation | Required |
| `dose_timestamp_s` | s (sim) | Timestamp of the dose integration | observation | Required |
| `dose_rate_uSv_h` | µSv/h | **Total** gamma reading at the detector pose: background 0.10 µSv/h plus all packages, attenuated, Poisson count noise. It is not a per-package value | observation | Required. Shown `UNAVAILABLE · no feed` until a reading arrives |
| `dose_integration_s` | s | Counting window (2 s) | observation | — |
| `mission_dose_mSv` | mSv | Trapezoidal integral of the noisy reading since the first sample | observation | — |
| `temperature_c` | °C | Ambient air at the robot. The model blends 19 °C (LLW side) to 20 °C (ILW side) across x = 10–14 m, with noise | observation | — |
| `relative_humidity_pct` | % | Ambient RH: 62 % to 66 % with the same blend | observation | — |
| `hydrogen_ppm` | ppm or `null` | Local H₂ at the gas inlet after travel delay and the t90 = 5 s response | observation | **`null` when `hydrogen_status` is `below_detection`.** The console shows `< 2 ppm · BELOW DETECTION`, never 0, and rejects `below_detection` with a number |
| `hydrogen_status` | `detected` \| `below_detection` | Whether the instrument resolved a concentration ≥ the limit | observation | Below detection does not prove absence |
| `hydrogen_detection_limit_ppm` | ppm | Synthetic limit (2 ppm, `physical_config.json` `sensor.gas_detection_ppm`) | observation | — |
| `gamma_xyz_m`, `gas_inlet_xyz_m` | m, world | Detector and inlet poses used for this sample. A gamma reading belongs to this pose, not to a drum | observation | Required by the console contract |
| `methane_ppm`, `methane_status`, `methane_detection_limit_ppm` | ppm | **Optional future channel.** The current backend outputs no methane (scenario methane generation is 0) | observation | Status `N/S` when a feed omits it; `—` with no feed |
| `pressure_kpa` | kPa | **Optional future channel.** Ambient air pressure. Not produced by `WarehouseSensors` today | observation | Same as methane |

### 2b. Directional gamma — `gamma_bearing`

**Source.** `WarehouseSensors.gamma_bins(position, yaw_rad)`.

| Key | Unit | Meaning | Visibility | Missing |
|---|---|---|---|---|
| `bearing_frame` | `robot_yaw` | Bin 0 = robot forward, counter-clockwise | observation | — |
| `bin_count` | 16 | — | observation | — |
| `intensity_uSv_h[16]` | µSv/h | Blurred synthetic bearing cue (25/50/25 % spread). It **carries no source identity** | observation | Panel shows "No directional gamma source connected" |
| `detector_xyz_m`, `yaw_rad` | m, rad | Pose the bins were computed at | observation | Required |

### 2c. Images — `camera_frame`

**Freshness.** 5 s.

| `camera_id` | Source | Meaning | Missing |
|---|---|---|---|
| `rgb` | Isaac Spot body camera (`robot.attach_cameras`) | RGB frame. Detector boxes attach to `frame_id` | Empty state "RGB — no frame" with the feed status |
| `depth` | Isaac optical depth (m) | Use for deformation evidence: compare silhouette/depth to the nominal profile | Same |
| `lwir` | `WarehouseSensors.thermal_from_camera(optical_depth, segmentation, intrinsics, camera_to_world)` | **Apparent** °C (grey-body, emissivity- and reflection-affected, 0.1 °C noise); NaN = missing depth. It does not reconstruct internal temperature. Must carry `units: "apparent_c"` and `range` | Same; the schema rejects LWIR without units and range |
| `third_person` | Isaac chase or overview camera | Main viewport | Offline: static Isaac RTX still labelled `STATIC REFERENCE · NOT LIVE` |

Every frame carries `frame_id`, `t_sim_s`, `width`, `height`, `encoding` and `uri`. It may also carry `fps`, `intrinsics` and `camera_to_world`. The segmentation used by `thermal_from_camera` is backend-only and is never forwarded.

### 2d. Localized wipe — `swab_result`

**Source.** `WarehouseSensors.start_swab(contact_xyz, time_s, robot_xyz, robot_stopped=True)` and `poll_swab(time_s)`. This is a virtual tool with 10 s dwell, 0.8 m reach and floor contact.

| Key | Unit | Meaning | Missing / special |
|---|---|---|---|
| `status` | `complete` | Only completed results are sent | — |
| `time_s`, `contact_xyz`, `area_cm2` | s, m, cm² (100) | The **one floor footprint** sampled | — |
| `alpha_bq_cm2`, `beta_gamma_bq_cm2` | Bq/cm² or `null` | Estimated removable activity in the footprint (recovery 0.55, count noise) | `null` with `*_status: below_detection`; shown `< MDA · BDL` |
| `alpha_status`, `beta_gamma_status` | `detected` \| `below_detection` | — | — |
| `*_detection_limit_bq_cm2` | Bq/cm² | 0.03 α, 0.15 β/γ | — |
| `near_package_id` | printed code | Optional association (console addition) | Drum detail also matches by distance |

A wipe does not characterise the whole package, and contamination is independent of rust and of the package's gamma source.

### 2e. Interpretations: separate records that point to observations

| Record | Key fields | Rules |
|---|---|---|
| `detection` | `detection_id`, `camera_id`, `frame_id`, `class_id` (0 drum, 1 corrosion, 2 bulge, per `DEFECTS.md`), `bbox_px`, `confidence`, `model_id`, optional `drum_attribution {package_id, status: attributed \| inconclusive, evidence}` | `confidence` belongs to the detection, not the drum. Attribution needs its own evidence (e.g. printed code read in a frame) and can stay inconclusive. The YOLO26s training set (`barrels_v2_1200`) is LLW-only; ILW pitting and lobes are out of distribution |
| `inspection_record` | `run_id`, `package_id`, `frame_id`, `view`, `finding` | One accepted entry from `WarehouseObservations.accept()`. Coverage per package: no records → `unseen`; any → `seen`; `front` **and** `oblique` → `inspected`. This is the only input to coverage counts |
| `inspection_finding` | `finding_id`, `package_id \| null`, `status: observation_only \| inconclusive \| finding`, `summary`, `evidence[]`, `limits[]`, `assessment: null` | Evidence summary, not a diagnosis. `assessment` is reserved for a future service |
| `assessment` | `assessment_id`, `run_id`, `package_id`, `tier`, `status: ok \| unsure \| defect`, `defect_types`, `reason`, `evidence_frame_ids`, `model_sha256?`, `shapes[] {camera_id, frame_id, bbox_px}` | One record per package result for the camera result layer and the map (green / yellow / red). `ok` = OK in inspected views; it cannot come from an empty detector response or incomplete coverage. Separate from coverage. The raw evidence view stays available |
| `alert` | `alert_id`, `severity`, `title`, `package_id?`, `evidence[]`, `proposed_action {text, status: "proposed_not_sent"}` | Proposals are displayed only. The console never sends commands. Acknowledgement is local |

**Freshness.** Records are kept as history. Out-of-order or late records are flagged and do not change "current" values.

### 2f. Robot and run telemetry (not per drum, listed for completeness)

- `robot_pose`: `xyz_m`, `rpy_deg`, `frame`, `nav_confidence`, `battery_pct`, `battery_runtime_s`, `health`, `operating_mode`, and `pose_source`. `pose_source: simulator_pose` is labelled as smoke-test pose. Freshness 3 s.
- `run_state`: `run_id`, `sim_clock_s`, `waypoint`, `target_package_id`, `planned_path` (node names) or `planned_path_m` (XY points), and `planned_packages`. Freshness 10 s. The header shows elapsed time only when `sim_clock_s` exists.

---

## Layer 3 — Private simulator and evaluator truth (never public)

**Sources.** `warehouse_physics.generate_inventory(layout, seed)` and `_drum_record()`; `gas_state()`; and `drum_faults.generate_session(output, seed=, manifest=)`. All are written to the evaluator manifest passed as `--fault-manifest`, or by default `sim/out/environment/evaluator/<uuid>.json`, which is git-ignored. `sim/build_environment.py` records the manifest path in `build_report.json`, so treat build reports as simulator-side too.

**Manifest layout** (`schema_version` 2):

```
{ "schema_version": 2,
  "seed": <int>,                       # session seed; replays everything
  "drums": [ ...visual-fault subset... ],      # legacy list: only drums with rust or bulge
  "physical_inventory": {
      "schema_version": 1, "seed": <int>,
      "drums": [ ...all 420, including clean... ],
      "sensor_config": { ...physical_config.json "sensor"... } } }
```

- **Top-level `drums`.** The older visual-fault subset, kept for earlier tooling. Entries: `drum_id`, `category`, `prim_path`, and optionally `corrosion {severity, sites[{feature, u, height_fraction}], body_uv_attack_fraction}` and `bulging {severity, peak_radial_displacement_mm, peak_height_fraction, azimuth_rad, shape}`. Omitted IDs are clean. For seed 42 it lists 108 affected drums (`checks/physical-isaac-summary.json`).
- **`physical_inventory.drums`.** Every package keyed by `drum_id`, clean ones included. `generate_session` attaches the same `appearance` block to affected entries. This is what `WarehouseSensors.from_manifest()` loads.

Visibility for every field below is **private**: never on the console, never in fixtures or logs. Freshness is per session; values are fixed at generation, and gas terms evolve with `gas_state(gas, elapsed_s)`.

| Key (in `physical_inventory.drums[]` unless noted) | Unit | Meaning |
|---|---|---|
| `drum_id`, `prim_path`, `category`, `xyz_m`, `radius_m`, `height_m`, `face_sign`, `yaw_rad` | — | Copies of public identity and geometry, used by the backend (not secret on their own) |
| `waste_form` | enum | LLW `dry_soft_waste` / `metal_offcuts` / `conditioned_filters`; ILW `grouted_mixed_metal` / `immobilised_sludge` / `grouted_compacted_pucks` |
| `net_mass_kg` | kg | LLW 35–180, ILW 560–1050 |
| `age_years` | years | 1–24 |
| `fill_fraction` | 0–1 | 1 − headspace / nominal volume |
| `activity_bq {Cs137, Co60, alpha_equivalent, beta_equivalent}` | Bq | Synthetic activity pools; α/β pools are equivalents, not nuclides |
| `scenario` | enum | Generator cause: `ordinary`, `exterior_corrosion`, `residual_deformation`, `solid_expansion`, `restricted_vent`, `breach`, `warm_venting`, `warm_no_release`, `cool_venting`, `gamma_outlier`, `transfer` |
| `exterior {exposure, attack_index}` | enum, 0–1 | Exterior corrosion exposure and attack index |
| `visual_plan {corrosion_severity, bulging_severity}` | 0–1 | Severities that drive the USD overlay |
| `radiation.unshielded_strength_usv_h_m2` | µSv/h·m² | Source term |
| `radiation.effective_attenuation_m_inv` | m⁻¹ | Shielding (LLW 0.7–3.2, ILW 12–19) |
| `radiation.isolated_aisle_face_1m_usv_h` | µSv/h | Reference dose 1 m from the face, no neighbours |
| `thermal.decay_heat_w`, `thermal.chemical_heat_w` | W | Deposited decay heat; chemical heat (6–13 W for warm scenarios) |
| `thermal.ambient_c`, `thermal.relative_humidity_pct` | °C, % | Per-drum ambient |
| `thermal.shell_c`, `thermal.internal_c`, `thermal.vent_c` | °C | **True** shell, internal and vent temperatures |
| `thermal.hotspot_delta_c` | °C | Local warm-patch amplitude |
| `thermal.emissivity` | 0–1 | LLW ≈ 0.87, ILW ≈ 0.48 |
| `gas.headspace_m3` | m³ | Headspace volume |
| `gas.vent_state` | `sealed` \| `filtered` \| `restricted` \| `open_release` | Vent state |
| `gas.temperature_k` | K | Headspace temperature |
| `gas.h2_ml_stp_day`, `gas.methane_ml_stp_day` | mL STP/day | Generation rates (methane 0) |
| `gas.h2_exchange_per_day`, `gas.pressure_relaxation_per_day` | day⁻¹ | First-order exchange and relaxation |
| `gas.elapsed_before_launch_days` | days | Episode age at launch |
| `gas.initial_air_mol` | mol | Initial headspace air |
| `gas.vent_xyz_m` | m | Vent location (gas source position) |
| `gas.pulse_h2_mol_s`, `gas.pulse_duration_s`, `gas.pulse_reservoir_mol` | mol/s, s, mol | Finite release pulse and its reservoir |
| `gas.h2_headspace_ppm` | ppm | **Internal** headspace H₂ (from `gas_state`) |
| `gas.gauge_pressure_kpa` | kPa | **Internal** gauge pressure |
| `gas.h2_emission_mol_s` | mol/s | Release rate |
| `containment.breached` | bool | Breach state |
| `containment.patches[] {xyz_m, radius_m, alpha_bq_cm2, beta_gamma_bq_cm2}` | m, Bq/cm² | Removable floor contamination patches |
| `appearance.corrosion {severity, sites[], body_uv_attack_fraction}` | — | Rendered rust: severity, anchor locations, coverage |
| `appearance.bulging {severity, peak_radial_displacement_mm, peak_height_fraction, azimuth_rad, shape}` | mm, — | Measured deformation (`centered_sidewall_expansion` LLW, `localized_shell_lobe` ILW) |
| manifest `seed`, `physical_inventory.seed` | int | Replays the whole session |
| `physical_inventory.sensor_config` | — | Copy of `physical_config.json` `sensor` |

Also private: `checks/physical-sensor-calibration.json` (seed-42 aggregates such as restricted-vent pressure and gas traces), the USD session overlay internals, and raw Replicator semantic IDs.

---

## Evidence is not diagnosis

The console keeps observations, interpretations and (future) assessments as separate records and never infers layer-3 values. The generator deliberately creates overlapping observations:

- Rust and contamination are independent. Rust can appear on a cool, intact drum.
- A bulge can come from residual deformation, ILW solid expansion or a restricted vent. A bulged drum can be cool, with hydrogen below detection in the surrounding air. Internal pressure and headspace composition are simulator truth.
- Total dose sums every package, so elevated gamma near a drum does not attribute it. The bearing bins carry no identity.
- Apparent LWIR depends on emissivity (LLW ≈ 0.87, ILW ≈ 0.48), view angle and reflections. Corrosion raises local emissivity.
- A wipe samples one 100 cm² floor footprint.
- LLW and ILW have distinct generated profiles, but their observations overlap.
