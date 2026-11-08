# Demo video plan: dense aisle inspection

Owners: **Tika** (sim, agent, HUD, final video) and **Param** (detector data, fine-tune, API).
Agreed 2026-11-08. This replaces earlier demo goals. If something here conflicts with older docs, this wins.

## What we are making

A video of about 2 minutes. Spot walks one aisle section of the dense warehouse and inspects every visible drum.

- **Route:** fixed. No floor-map planning and no path choice.
- **Agentic part:** the robot decides which drums deserve a **second look**, and skips the rest. Second looks cost time, so the agent has to be efficient. We score it on faults found per second look.
- **Minimap:** every drum starts grey. As the robot clears or condemns it, it turns green or red.
- **Camera:** fixed to the body. To look at higher tiers, the robot pitches its body up while standing still. The camera never moves on its own.
- **Faults:** randomised per run from a seed. The agent never sees ground truth.
- **Radiation:** no retreat, no dose stop, no radiation alert. Gamma is still measured, shown on the HUD and used as evidence.

## Section

The section is branch `codex/dense-warehouse`, aisle 2 (y = 6.0), LLW zone.

| | |
|---|---|
| Pallets | 5 per side at x = 3.1, 4.4, 5.7, 7.0, 8.3. Each is 2×2 drums, stacked 3 tiers high |
| Drums | 120 in total. **60 face the aisle** and form the job. The 60 behind them are hidden (shown as "not visible", excluded from the job) |
| Front faces | Row B-R at y = 4.95, row B-L at y = 7.05. Clear width between drum faces is 1.5 m |
| Drum centre height | Tier 1 at 0.58 m, tier 2 at 1.61 m, tier 3 at 2.63 m |
| Column x | 2.79, 3.41, 4.09, 4.71, 5.39, 6.01, 6.69, 7.31, 7.99, 8.61 (the same on both sides) |

## Camera and viewpoints (shared contract)

Param's training renders and Tika's agent must use **exactly** this camera and these viewpoints. It lives in one file, `sim/inspection_viewpoints.py`. Tika writes it first (T1), and Param's generator imports it.

- **Intrinsics:** the same as training. 640×640, fx = fy = 400, 77.3° horizontal and vertical FOV.
  - This replaces the current agent camera (640×360, focal 15).
- **Mount:** 0.35 m ahead of the body centre and 0.45 m above it. Eye height is about 0.95 m.
  - The mount is level (0° pitch). It is currently tilted 18° down, which would put tier 3 out of view.
- **Inspection view:**
  - The robot stands on the aisle centre line, 1.5 m before the column (in x).
  - It yaws ±35° towards the row, then pitches its body up to +10° and holds for 1 s.
  - The view distance is about 1.8 m, and one frame contains all 3 tiers of that column. Tier 3 is at +43°, tier 1 at −11°.
  - Facing a row square-on would put the camera 0.7 m from the drums, too close to see tier 3. That is why the view is diagonal.
- **Body pitch:** Isaac's Spot walking policy has no pitch input. While standing, we pitch the camera mount about the body origin, label it "body pitch (simulated)" on the HUD, and keep it within ±0.3 rad, which a real Spot can do.
- **Second look:** the robot steps 0.5 m closer along the aisle and views the target drum from about 1.3 m at a new yaw. One drum per second look.

## Drum status

| Status | Meaning |
|---|---|
| Grey | Not yet seen clearly |
| Amber | Suspected (one weak YOLO frame, or a sensor anomaly without a visual). A second look is pending or the agent declined one |
| Green | Seen clearly in at least 2 frames with no fault. Thermal reading normal |
| Red | Confirmed fault: YOLO rust or bulge on 2 views, or heat or gas attributed to this drum |

## Workstreams

### Tika: sim, agent, video

- **T0. Consolidate the code.** Commit the uncommitted work in `../agentverse26-dense` as it stands. Merge `main` in: body-fixed camera, scan turns, extra per-frame logging. Work on branch `demo/dense-aisle`.
- **T1. Camera and viewpoints file.** Write `sim/inspection_viewpoints.py` (camera intrinsics, mount, viewpoint list for the section, pitch helper). Switch the agent's onboard camera to it. **Push this first: it unblocks Param.**
- **T2. Route and scan.** Walk x = 1.3 → 8.3 on y = 6.0. At each pallet, take the inspection view of both rows. Remove `drive()`'s pass-through checkpoint logic.
- **T3. Remove the radiation behaviour.** Delete the dose stop, the `retreat_alert_*` action, the dose back-off check in `offered_actions`, and `dose_source_scale`. Gamma stays in readings and on the HUD.
- **T4. Seeded faults and ground truth.** A seed picks 4–6 faulty drums among the 60. Each gets a random fault: rust (defects overlay), bulge (deformed mesh), heat (+8 to +30 °C) or H2 vent. Write ground truth to `out/.../truth.json`, which only the scorer reads.
- **T5. Check the emitters.** Every drum in the section has gamma, temperature and gas values, and the HUD reading visibly rises near the drum that causes it. Produce one plot per channel along the route.
- **T6. Second look as the agentic decision.**
  - Offer `second_look_<code>` only for amber drums.
  - Change the Cosmos prompt to: "budget is limited; spend second looks only where the evidence is ambiguous".
  - Log every decision with its evidence.
  - Scoring: faults found, false reds, and second looks used.
- **T7. HUD and minimap.**
  - Main panel: the onboard camera with YOLO boxes.
  - Minimap: the 60 drums as a 2-side × 10-column × 3-tier grid, plus the robot position.
  - A decision panel: the latest Cosmos choice and its reason.
  - A sensor strip: gamma, thermal, H2, hiss.
  - Remove the third-person view if it costs space.
- **T8. Final video.** Run 3 seeds and pick the clearest. Check:
  - every visible drum ends green or red;
  - every red matches truth;
  - every second look was justified.
  - Publish the MP4 and the report.

### Param: detector

- **P1. Dense training renders.**
  - Render from the viewpoints in `sim/inspection_viewpoints.py`, adding jitter: ±0.3 m position, ±10° yaw, 0–15° pitch.
  - Use the dense section and the same fault generators as T4: rust overlay, bulge mesh.
  - Randomise faults, lighting and paint shade.
  - Label every visible drum and fault, on all tiers.
  - Target: 3,000 or more images, with held-out seeds for test.
- **P2. Fine-tune YOLO26s** from the current weights on P1 together with the existing v2 set, so floor-level drums don't regress.
  - Report recall and precision per tier and per class at the current API thresholds.
  - Target: corrosion and bulge recall ≥ 0.8 at precision ≥ 0.8 on tiers 1–3.
- **P3. Redeploy the API** with the same request/response contract (`/predict`, `band`, `confidence`), so `scripts/hot/yolo.py` needs no changes. Bump the `run_id`.
- **P4. Smoke test on agent frames.** Run the new model on 20 frames saved from a T2 run. Post a contact sheet in `docs/validation/` showing boxes on all tiers.

## Order and dependencies

```
T0 → T1 ──→ P1 → P2 → P3 → P4 ─┐
      ├──→ T2 → T5             ├──→ T8
      └──→ T3, T4 → T6 → T7 ───┘
```

- T1 is the only thing Param waits on. Everything else runs in parallel.
- Until P3 lands, T6 and T7 run on the current model. Expect misses on tiers 2–3, which will show amber or grey.

## Risks

- **Modal spend limit.** It blocked every job on 2026-11-08. P1, P2 and every video run need it raised.
- **Tight aisle.** Spot is about 1.1 m long and the clear width is 1.5 m. Turning ±35° in place should fit. Check that LiDAR navigation doesn't drift into the pallets during scans.
- **Simulated body pitch.** It is not physical in the walking policy. Keep it labelled so the video does not overclaim.
- **Cosmos Reason 2.** It is a small model and has embellished its reasons before. Keep its reasons tied to logged evidence, and show the evidence on the HUD next to the reason.
