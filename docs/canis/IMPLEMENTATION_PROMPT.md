# Prompt for the agent integrating C.A.N.I.S.

Copy this file into your agent's task. Give it access to your existing simulator, robot, detector and mission code, plus this console branch.

## Objective

Integrate the C.A.N.I.S. operator console with our existing warehouse system. Keep the current simulator, robot controller, recognition models and mission logic as the producers. Add a thin adapter that publishes their real observations in the console's `canis.v1` format. Keep the console read-only. Work on an integration branch in our system.

## Get the console running

```sh
git clone --branch levi/canis-operator-console --single-branch https://github.com/tika/agentverse26.git canis-console
cd canis-console/canis
npm ci
npm run dev
```

Use Node 22. Open `http://localhost:5178/?mode=replay` first to check the UI with the built-in fictional demo. The root URL opens offline with a static public map. The console checkout includes the warehouse map and brand sources required by its build. Keep it alongside our system so we can integrate over WebSocket without copying simulator code.

Read [console README](../../canis/README.md), [feed checklist](INTEGRATION_CHECKLIST.md), [data dictionary](DATA_DICTIONARY.md), and [the executable schemas](../../canis/src/contracts/messages.ts). Treat the schemas and [ingest implementation](../../canis/src/ingest/FeedBus.ts) as authoritative.

## Connect our system

1. Inventory the real producers and document the source of each feed. Start with one RGB capture and a matching measured detection, then add the other feeds. Implement the adapter beside the producers. The console opens WebSockets as a client and receives one JSON envelope or an array of envelopes per text message. It does not send commands.
2. Configure the browser with `http://localhost:5178/?mode=live&feeds=isaac=ws://127.0.0.1:8765,robot=ws://127.0.0.1:8766,sensors=ws://127.0.0.1:8767,detector=ws://127.0.0.1:8768,mission=ws://127.0.0.1:8769,assessment=ws://127.0.0.1:8770`. Substitute the actual browser-reachable addresses. The Vite app and adapter are separate processes. For HTTPS deployments use browser-reachable WSS endpoints and keep any detector credentials in the producer or relay.
3. Publish `camera_frame` for `third_person`, `rgb`, `depth`, and `lwir`. Use a browser-loadable image URI, the actual dimensions and encoding, and stable capture IDs. Send depth in metres with `units: "depth_m"` and its display range. Send colour-mapped apparent thermal as a PNG or JPEG with `units: "apparent_c"` and `range: [low, high]`. Retain raw depth and thermal arrays separately for evidence. Send `robot_pose` in metres and degrees in `world_m_zup`. Publish `run_state` with the actual simulation clock, run ID, mission phase, and reason for any hold. Verify the map hash against the scene used by the producers. The static overhead image and its projection are calibrated to the bundled warehouse.
4. Give each message `schema: "canis.v1"`, `kind`, `source: {id, kind}`, `seq`, and `t_sim_s` when available. Use a source ID that is unique to the producer session if sequence numbers reset. Increase sequence numbers per source ID and message kind, and per camera for `camera_frame`. Do not restart detector sequences per image. Use the captured simulation timestamp on delayed results. Give the same capture the same `frame_id` in camera messages, detections, and ledger evidence.
5. Send `detection` per measured box with `class_id` 0 drum, 1 corrosion, or 2 bulge, `bbox_px: [x, y, width, height]` in source image pixels, `confidence`, and `model_id`. A detection only overlays its exact image. Keep detector I/O off the physics loop with bounded newest-frame buffering. If tracking is available, publish separately labeled tracked previews using `model_id: "optical-flow-preview"` or `quality: "degraded"`. Exclude previews from inspection evidence.
6. Key drum identity by the printed package code, e.g. `A-L-01-T1`, including a depth suffix where printed. Require image evidence and independent tier geometry before accepting an observation. Unresolved labels stay unresolved. Emit `inspection_record` only for accepted evidence. One accepted view gives seen coverage, and accepted front plus oblique views give inspected coverage. Make ledger writes idempotent by run, package, and frame. Publish the separate `assessment` event with package, tier, status, reason, evidence frame IDs and exact-frame result shapes. It drives camera and map condition together. Use `unsure` with a reason when evidence is incomplete. An empty detector result cannot establish OK. Defect requires supporting evidence and one or more of `corrosion` or `bulge`.
7. Keep the private simulator manifest, hit IDs, seeded conditions, evaluator truth, and secrets out of the browser payload, build, recordings and Git. Publish only allowlisted map geometry and public observations. Use the `simulator_pose` tag for a labelled locomotion diagnostic and `estimated` for robot localisation. Keep fictional demo data visibly labelled. If replaying real evidence over WebSocket for debugging, identify it explicitly as recorded in the operator view and handoff, since the live adapter itself selects the LIVE UI.

## Show the integration works

Run the console's `npm run check` with Google Chrome installed. In the existing console, verify an exact-frame detector overlay, raw-view toggle, sensor units and frame updates. Send an accepted record and assessment for the same verified printed code, then confirm its camera result and exact map tier agree, coverage stays independent of condition, and repeated delivery does not double-count. Exercise an unreadable label and a disconnected feed. Report measured browser frame gaps and inference latency through a turn and identify which data is live, recorded or fictional. Include the exact startup commands, feed URL, source-to-message mapping, test results, and any producers still missing. Do not claim the closed-loop patrol or policy has passed based on the offline or demo views.
