# Stage 1 contract and model-access audit

Claude Code, 7 November 2026, prompt v1.1. Branch `claude/s1-contracts` from upstream
main `f1a288b` (13 commits after the prompt's last verified `e529ca0`, which is an ancestor).
CPU only. No Modal job launched by Claude.

## Delivered

| File | Purpose |
| --- | --- |
| `perception/contracts.py` | Versioned (`1.0.0`) validators: sensor sample, cumulative-dose oracle, detection, inspection record, high-level proposal, location codes, yaw normalisation. Pure Python. |
| `perception/sim_adapter.py` | Renames `SensorWorld.sample()` output (flat f1a288b form **and** Codex S1 `gamma` packet) into contract messages. No physics. |
| `perception/tests/test_contracts.py` | 34 tests: dose integration (both methods), oracle detects mSv/uSv mix-up and decreasing totals, stale/future/saturated/failed readings, hydrogen scope + detection limit, class order, box bounds, truth/probability leakage, ranking-not-probability priority, ambiguous identity, correlated-confidence product rejected, location code consistency, offered-goal/evidence/safety-override checks, yaw. Includes a conformance run of the existing simulator. |

Run: `python -m unittest discover -s perception/tests -v` (needs NumPy only for the simulator conformance tests). Result: 34/34 pass; existing `sim/tests` 9/9 pass.

## Contract decisions (need Codex review before merge)

1. **Detection message** keeps `class`, `drum_id`, `xyxy` from `boxes.json`; adds `class_id`, `confidence`, `frame_id`, `camera_id`, `timestamp_s`, `image_size_px`, `model{name,revision}`. A non-null `drum_id` must name its `association` (`plate_read`, `geometry_map`, `track`). Probability, severity, priority and truth are forbidden fields.
2. **Sensor sample** requires `kind`, `source` (`robot`|`facility`), `units`, `pose{frame,xyz_m[,yaw_rad]}`, `sample_age_s`, `validity` (valid, stale, saturated, below_detection_limit, failed, calibration_expired, warming_up), `uncertainty.std`, `status`. Gamma requires `saturation_limit`; hydrogen requires `measures` (`ambient`|`package_headspace`) and `detection_limit`.
3. **Cumulative dose** is published in uSv with `integration_method` (`left_rectangle` = prompt formula, or `trapezoid` = current sim) and `simulated_proxy: true`. An interrupted integral stays a valid **lower bound** with `complete: false`.
4. **Inspection record v1** is separate from detections: immutable `drum_id`, `legacy_id`, full location (lane/side/column/tier/tier_count/stack_id/base_z/location_code, cross-checked against the code), identity status with candidates, coverage fraction, finding tracks with `frames` and `distinct_views` (no combined probability), `condition_status` that has no "safe" value, `priority{kind: ranking_score, index 0–100, breakdown}`, optional `calibrated_probability` only with target event, domain and held-out evaluation reference.
5. **Proposal** (Cosmos or rules) must choose an offered goal, cite known evidence IDs, and cannot replace a safety `retreat`/`hold_alert`.

## Review of Codex S1 gamma packet (`codex/stage-1-runtime` @ e373e0f)

Ran Codex's `sim/sensors.py` read-only through the adapter: no schema errors, oracle conforms, outage marks `dose_complete=false`. Mapping: `unit→units`, `age_s→sample_age_s`, `position_m→pose.xyz_m`, `uncertainty_uSv_h→uncertainty.std`, `status ok/failed/saturated→validity valid/failed/saturated`. No change required for the adapter.

Requested change: **while saturated, the integrator adds nothing** (`current_rate=None`), so cumulative dose is under-counted exactly in the highest field. Suggest integrating at `saturation_limit` as a lower bound and keeping `dose_complete=false`. (From reading the code; the test path did not reach 1000 uSv/h.) Also please add `saturation_limit` and pose yaw to the packet.

## Codex review outcome (board 19:28:06) — applied in follow-up commit

- Adapter no longer substitutes world origin: a sample without `position_m` requires a caller pose; a caller pose that disagrees with the packet is rejected.
- Unknown uncertainty is `{"std": null, "status": "unknown"}`, distinct from a measured `0`. Failed readings and the (unmodelled) integral use it.
- Cumulative dose requires `complete`; `complete=false` cannot report `status: ok` and is published as `incomplete_lower_bound`. The S1 baseline integral excludes invalid intervals and latches incompleteness; this is preserved, not presented as exact exposure.
- Codex will add saturation setting and yaw at the capture boundary.

## Audit findings

| # | Finding | Impact | Owner/next |
| --- | --- | --- | --- |
| A1 | `sim/drums.json` mixes runtime-permitted fields (id, x/y, yaw, dims, category) with hidden truth (`faults`, `defects`, `state`, `corrosion_severity`, `internal_corrosion`, `obstructed`). | Truth leakage risk into perception/policy. | Codex: emit a runtime asset map; Claude: perception loads only that. Stage 2. |
| A2 | `scripts/spot_rollout.py` writes `scene_truth.json` beside `samples.jsonl`. | Loaders that glob a run dir can read truth. | Keep evaluator-only; Claude's loaders will refuse it. |
| A3 | `spot_agent.py` safety limits use `sim_rad`/`sim_heat` units; `criteria.py` uses uSv/h and mSv. | Two unit systems for one safety decision. | Migrate the planner to contract messages (stage 6/7). |
| A4 | `drums.json` yaw values exceed π (e.g. 4.86 rad). | Fine in-scene; normalise at interfaces (`normalize_yaw_rad`). | Adapters. |
| A5 | Plate reader accepts `^[A-Z][0-9]{2}$`. | Additional upper-tier IDs must stay in that form, or the regex must change with the stage-2 ID scheme. | Agree in stage 2. |
| A6 | `tools/train_spot_lora.py` hard-codes `gpu="H100"` and a Modal secret `huggingface`. | Workspace `levi-stein-26` has **no secrets and no volumes**; LoRA training would fail. LoRA is out of scope until stage 7 anyway. | Do not run. Re-target RTX-PRO-6000 if ever needed. |
| A7 | `source_strength` is labelled "uSv/h at 1 m" in config text. | Declared synthetic calibration exists in config text only. | Codex to keep the declaration in the packet/README. |
| A8 | No YOLO weights, training code or `perception/` existed before this branch. | Stage 4–5 work starts from zero. | Claude. |

## Model access (checked 19:2x GMT, public Hugging Face API, no token sent)

| Model | Gated | Notes |
| --- | --- | --- |
| `nvidia/Cosmos-Reason2-2B` (used by `spot_agent.py`, `train_spot_lora.py`) | yes, `auto` (accept licence) | Needs Levi's HF account to accept the licence and an `HF_TOKEN` Modal secret. |
| `nvidia/Cosmos-Reason2-8B` | yes, `auto` | Same. |
| `nvidia/Cosmos-Reason1-7B` | no | Fallback if Reason2 access is not granted. |

**Blocker for stage 7 (not stage 1):** Levi needs to accept the Cosmos-Reason2 licence on Hugging Face and create a Modal secret named `huggingface` with `HF_TOKEN`. Not required now.

YOLO: Ultralytics nano weights are publicly downloadable; install only in a separate training image, never Isaac's Python.

## Rubric → contract coverage

| Criterion (weight) | Where the contract supports it |
| --- | --- |
| Perception-driven action (25%) | Proposals must cite evidence IDs that exist in the run's records. |
| Adaptation to change (25%) | Validity/staleness fields and the safety override rule make a mid-run change traceable. |
| Operational autonomy (15%) | Model name/revision on every detection and proposal; latency logging slot in stage 7. |
| Relevance and impact (20%) | Dose rate + cumulative proxy; hydrogen ambient vs headspace; no "safe" status. |
| Ambition/technical quality (15%) | 30 contract tests; conformance oracle for the simulator. |

## Limitations

Contracts are a draft for partner review. No detector, tracker or Cosmos inference exists yet. The thermal channel is not yet a contract kind beyond `temperature`.
