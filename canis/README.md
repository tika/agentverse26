# C.A.N.I.S. operator console

**Containment Analysis & Nuclear Intelligence System.** This is a read-only operator interface framework for the Agentverse 420-drum warehouse (`sim/warehouse-v3`). It opens locally with no Isaac, robot, detector, model weights, credentials or backend. By default it shows **`FRAMEWORK · OFFLINE`**.

## Start

```sh
cd canis
npm install
npm run dev          # http://localhost:5178
```

`npm run dev` first rebuilds `public/data/warehouse-map.public.json` from `../sim/warehouse-v3/map.json`, using an allowlist of public fields. It needs Node 18+ and was tested with Node 22.16.

## Modes

| Mode | How | What you see |
|---|---|---|
| Offline framework (default) | `/` | Real map and inventory (420 drums, 336 LLW / 84 ILW, 56 racks), logos, and the Isaac RTX roof-off still marked `STATIC REFERENCE`. Every feed is `NOT CONFIGURED`, live values are `UNAVAILABLE`, all drums are `UNSEEN`, and there is no clock |
| Demo replay | `/?mode=replay` or the header selector | Persistent `DEMO REPLAY · FICTIONAL FIXTURE DATA` banner and `FIXTURE` badges. A deterministic 60 s sequence on real map IDs with invented readings. Pause, resume and reset are in the header. `&tick=<ms>` changes speed and `&at=<s>` pauses at a replay time |
| Live adapter | `/?mode=live&feeds=isaac=ws://…,robot=ws://…` | Read-only WebSocket feeds; see `docs/canis/INTEGRATION_CHECKLIST.md` |

The replay demonstrates:

- readings and a below-detection H₂ result (`< 2 ppm · BELOW DETECTION`, never 0);
- a sensor gap that goes `STALE`;
- one duplicate, one out-of-order and one invalid message, rejected at the boundary and visible in Logs;
- detections tied to a specific frame;
- ledger coverage (front + oblique → inspected);
- an inconclusive gamma attribution and an inconclusive deformation finding;
- a `PROPOSED · NOT SENT` action.

**Mission ledger.** In offline or live mode, Inspection → *Load mission ledger checkpoint…* reads a `WarehouseObservations` checkpoint (`scripts/hot/warehouse_observations.py`) locally and shows real coverage.

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` / `build` / `preview` | Run or build. Both regenerate the public map first |
| `npm test` | Vitest: map fidelity vs `map.json`, geometry, ingest boundary, ledger compatibility, replay fixture |
| `npm run typecheck` | `tsc` strict |
| `npm run check:privacy` | Scans `public/`, `dist/` and `src/fixtures/` for private simulator-truth keys and evaluator paths |
| `npm run e2e` | Playwright against the dev server, using the installed Google Chrome (`channel: chrome`) |
| `npm run screenshots` | Writes `../docs/canis/screenshots/*.png` |
| `npm run check` | All of the above except screenshots |

## Layout

```
src/contracts/   canis.v1 message schemas (zod), public map types, private-key denylist
src/ingest/      FeedBus — the single ingest boundary (privacy guard, validation, dedupe, ordering, lateness), freshness rules
src/adapters/    StaticAdapter, ReplayAdapter, LiveAdapter, ledger checkpoint converter
src/fixtures/    demo replay timeline and generated placeholder frames (all fictional)
src/state/       store (useSyncExternalStore), types, React context
src/components/  Header, Viewport, RobotCamera, NavMap, RobotStatus, Sensors, InspectionMemory, DrumDetail, Alerts, Logs
src/tabs/        Simulation, Inspection, Sensors, Alerts, Logs
```

## Rules the code enforces

- **Truth stays private.** Only allowlisted `map.json` fields are published. Baseline placeholders such as `state: "clean"` and `faults` are dropped. Inbound payloads containing private keys are rejected and logged by key path only. See `docs/canis/DATA_DICTIONARY.md`.
- **Packages are keyed by printed location code** (`A-L-01-T1`), the same key the mission ledger uses. `D###` is shown alongside.
- **Coverage comes only from ledger records.** Confidence belongs to a detection, a gamma reading belongs to a detector pose, and package attribution may stay inconclusive. The `assessment` slot is reserved.
- **Read-only.** There are no command message types, acknowledgement is local, and proposed actions are labelled `NOT SENT`.

Brand assets in `public/assets/brand/` are byte-identical copies of `assets/canis logo.png` and `assets/canis_type.png`. The black artwork sits on a warm-yellow plate so it reads on the dark header.
