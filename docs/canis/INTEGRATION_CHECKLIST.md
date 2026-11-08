# C.A.N.I.S. future integration checklist

The console is a **read-only consumer**. Each source connects as its own WebSocket feed, and the console never sends anything back (no `send()` call exists in `LiveAdapter`). A disconnected feed affects only its own panels.

```
?mode=live&feeds=isaac=ws://host:8765,mission=ws://host:8766,robot=ws://host:8767,sensors=ws://host:8768,detector=ws://host:8769,assessment=ws://host:8770
```

You can also set `VITE_CANIS_FEEDS` (same syntax) at build time. Each socket frame is one JSON `canis.v1` message or an array of them. The schemas are in `canis/src/contracts/messages.ts`.

## Common envelope (every message)

```json
{ "schema": "canis.v1", "kind": "...", "source": { "id": "isaac-relay-1", "kind": "isaac" },
  "seq": 42, "t_sim_s": 128.4, "quality": "ok" }
```

- [ ] `seq` is monotonic **per source id and kind** (and per camera for frames). An equal `seq` is dropped as a duplicate. A lower `seq` is kept in history as out of order and never shown as current.
- [ ] `t_sim_s` is the simulation clock. Freshness is measured on it, so a paused sim does not look stale. A sample older than its freshness window on arrival is marked late.
- [ ] Positions are `world_m_zup` metres, the `map.json` frame (hall 24 × 28.30 m, origin at the hall corner, +X across, +Y along). Set `frame: "world_m_zup"` where the schema asks for it.
- [ ] Do not include private keys (`canis/src/contracts/private-keys.json`). The boundary rejects the whole message and logs only key paths.
- [ ] `source.fixture: true` is reserved for demo data. It is refused outside replay mode.

## Feed-by-feed

### Isaac (`feeds=isaac=…`)
- [ ] `camera_frame` with `camera_id: "third_person"` for the main viewport: `frame_id`, `t_sim_s`, `width`, `height`, `uri` (http(s), `blob:` or `data:`), and optionally `fps`.
- [ ] Optionally `map_snapshot` with `map_sha256` equal to the console footer, to confirm both sides use the same map.
- [ ] Freshness: frames 5 s.

### Mission / autonomy (`feeds=mission=…`; Codex lane `codex/warehouse-dog-inspection`)
- [ ] `run_state`: `run_id`, `sim_clock_s` (enables the header clock), `waypoint`, `target_package_id`, and `planned_path_m` (`warehouse_routes.route_from_spawn()` points) or `planned_path` (node names), plus `planned_packages`.
- [ ] `inspection_record`, one per `WarehouseObservations.accept()`: `run_id`, `package_id` (printed code), `frame_id`, `view` (`front` / `oblique` / …), and `finding`. Coverage follows `WarehouseObservations.coverage()`.
- [ ] Offline alternative: Inspection tab → **Load mission ledger checkpoint…** reads the checkpoint JSON through the same boundary.
- [ ] Freshness: run state 10 s.

### Robot (`feeds=robot=…`)
- [ ] `robot_pose`: `xyz_m`, `rpy_deg`, `frame`, `pose_source` (`estimated`, or `simulator_pose` for the locomotion smoke test, which is labelled as such), `nav_confidence`, `battery_pct`, `battery_runtime_s`, `health`, `operating_mode`.
- [ ] `camera_frame` with `camera_id` `rgb` and `depth` (depth `units: "depth_m"`, `range`). Include `intrinsics` and `camera_to_world` when available.
- [ ] Use the **same `frame_id`** in the ledger, the image file and detections.
- [ ] Freshness: pose 3 s, frames 5 s.

### Sensors (`feeds=sensors=…`): simulator-side relay around `WarehouseSensors`
- [ ] Run `WarehouseSensors.from_manifest(private_manifest)` **outside** the console and agent. Forward only return values.
- [ ] `sensor_reading` = `sample(robot_xyz, t, gamma_xyz=…, gas_xyz=…)` output, unchanged, plus `gamma_xyz_m` and `gas_inlet_xyz_m`. Keep `hydrogen_ppm: null` for below detection.
- [ ] `gamma_bearing` = `gamma_bins(position, yaw)` plus `detector_xyz_m` and `yaw_rad`.
- [ ] `camera_frame` `camera_id: "lwir"` from `thermal_from_camera(...)`, colour-mapped, with `units: "apparent_c"` and `range: [min, max]`. Never forward the segmentation.
- [ ] `swab_result` = completed `poll_swab()` output, with an optional `near_package_id`.
- [ ] Freshness: sensor 8 s.

### Detector (`feeds=detector=…`): YOLO26s `yolo26s_20261107T225757Z_d625ef`
- [ ] One `detection` per box: `detection_id`, `camera_id`, `frame_id` of the analysed frame, `class_id` (0 drum, 1 corrosion, 2 bulge), `bbox_px` (x, y, w, h in that frame's pixels), `confidence`, `model_id`.
- [ ] `drum_attribution` only with its own evidence (e.g. printed code read). Otherwise `status: "inconclusive"` and `package_id: null`.
- [ ] Remember the training set is LLW-only.

### Assessment (`feeds=assessment=…`)
- [ ] `assessment`, one record per package result, drives **both** the camera result layer and the map (Codex display contract `docs/warehouse_inspection_display.md`). Fields: `assessment_id`, `run_id`, `package_id` (printed code), `tier` (must match the code's `T#`), `status` `ok | unsure | defect`, `defect_types` (`corrosion`/`bulge`, required for and only allowed on `defect`), `reason`, `evidence_frame_ids` (≥ 1), optional `model_sha256`, and `shapes: [{camera_id, frame_id, bbox_px}]`. A shape is drawn only on the frame it references.
- [ ] `ok` means OK in inspected views. An empty detector response or incomplete coverage must not produce `ok`. Assessments never change coverage.
- [ ] Pre-assessment detections render as brand-yellow outline boxes. `model_id: "optical-flow-preview"` or `quality: "degraded"` renders dashed and labelled `TRACKED`, and is not evidence.
- [ ] `inspection_finding` (`observation_only` / `inconclusive` / `finding`) with `evidence` refs and `limits`. `assessment` stays `null` until the service contract is agreed.
- [ ] `alert` with `severity`, `evidence`, and optional `proposed_action.status: "proposed_not_sent"`.

## Acceptance before a real mission

- [ ] `npm run check` passes (typecheck, unit, build, privacy scan, e2e).
- [ ] Run each feed alone and disconnect it. Only its panels go to `DISCONNECTED`/`STALE`, and Logs records the transition.
- [ ] Send a deliberately leaky payload (e.g. with `gauge_pressure_kpa`). It is rejected with a `privacy` log entry.
- [ ] Load a real ledger checkpoint. Counts match `WarehouseObservations.counts()`.
- [ ] The detection overlay appears only on the matching `frame_id`.
- [ ] The map footer sha256 matches the `map.json` used by Isaac and the mission.

## Still to build (outside this console)

1. An Isaac relay process that publishes frames and the sim clock over WebSocket.
2. A simulator-side `WarehouseSensors` relay (backend stays private).
3. Robot pose, health and battery publishing. Until localisation exists, label simulator pose.
4. A ledger publisher (live `inspection_record` stream) from the Codex mission loop.
5. A YOLO26s detection stream keyed by `frame_id`.
6. An assessment service and its `assessment` contract.
