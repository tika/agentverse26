# YOLO26s results and version history — 8 November 2026

## Latest experimental: expanded 2,500-image fine-tune

**Used in the recent rigid-camera videos:** `compare_colors_20261108T053740Z_continued`, checkpoint SHA `ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a`. It is deployed separately; the previous model remains the repository default. [Exact URL, credentials and verification](LATEST_MODEL.md).

The release retains the original 1,500 mixed LLW/ILW frames, adds 750 yellow LLW and 250 blue-teal ILW frames, and totals 1,500 yellow + 1,000 ILW targets. Its split is 2,000 train / 235 validation / 265 test; scenes stay within splits and training is shuffled. Continuation from the previous best weights used 20 epochs, learning rate 0.0001 and one RTX PRO 6000: 68.78 seconds training, 76.57 seconds including evaluation. Validation selected this expanded candidate.

| Matched primary-target test group | Targets | Previous | Latest experimental |
|---|---:|---:|---:|
| Original yellow LLW | 75 | 96.0% | 97.3% |
| Original metallic / blue-teal ILW | 75 | 74.7% | 70.7% |
| Additional yellow LLW | 90 | 98.9% | 100.0% |
| Additional blue-teal ILW | 25 | 64.0% | 68.0% |
| All primary targets | 265 | 233/265 (87.9%) | 233/265 (87.9%) |

Confidence is 0.25 and matching IoU is 0.5; misses count as failures. Both models missed zero primary targets on this test. Latest all-box mAP50 / mAP50–95 is 82.9% / 78.3%; warm inference median / p95 is 6.06 / 6.28 ms. These metrics are synthetic, and the original ILW subset regressed. Do not describe the expanded model as universally better or promote it by changing the previous pointers. The latest-model guide lists saved weights, reports, predictions and known camera-test failures.

## Previous default: 1,500-image nano/small comparison

**Retained default: YOLO26s.** Nano's API is retired; its checkpoint and reports remain archived. The tables below are the original 150-frame comparison, not evaluation of the expanded model. No warehouse, robot-control or Cosmos code is changed by a detector release.

## Held-out synthetic test results

Both models used the same 150 test frames from five scene seeds excluded from training/validation. Targets are balanced across conditions, LLW/ILW categories and tiers 1–2. These are synthetic results, not real-world accuracy.

| Metric | YOLO26n | YOLO26s (selected) |
|---|---:|---:|
| Primary barrels correctly classified | 113/150 (75.3%) | 128/150 (85.3%) |
| Yellow LLW primary barrels | 96.0% (75 targets) | 96.0% (75 targets) |
| Metallic ILW primary barrels | 54.7% (75 targets) | 74.7% (75 targets) |
| All labeled barrels correctly classified | 1809/2484 (72.8%) | 1934/2484 (77.9%) |
| All-barrel mAP50 | 73.3% | 77.9% |
| All-barrel mAP50–95 | 66.6% | 72.8% |
| Primary barrels missed | 0 | 0 |
| Normal primary barrels falsely flagged | 7/38 | 5/38 |
| Training wall time | 86.8 s | 95.0 s |
| Training + evaluation wall time | 93.1 s | 101.5 s |
| Warm inference median / p95 | 6.12 / 6.43 ms | 6.22 / 6.45 ms |

Condition accuracy uses confidence ≥0.25 and box IoU ≥0.5, with missed detections counted as failures. All-barrel counts include small, clipped and partially occluded neighbours. mAP sweeps confidence and is a different metric from condition accuracy. There are no rust-patch counts in this model.

## Per-condition primary-barrel recall

| True condition | Targets | Nano correct | Small correct |
|---|---:|---:|---:|
| normal | 38 | 31 | 33 |
| rust | 37 | 23 | 34 |
| bulge | 38 | 31 | 34 |
| rust_and_bulge | 37 | 28 | 27 |

Small improves the overall result substantially, especially on metallic ILW drums. Combined rust-and-bulge remains a weak class. Both models are much stronger on the yellow LLW designs than metallic ILW; tiny/occluded background barrels are harder than the deliberately inspectable primary targets. The numbers above do not establish performance on real camera footage.

## Dataset and training

- 1,500 native 384×384 PNGs; four whole-barrel condition classes.
- 1,200 train / 150 validation / 150 test; 50 disjoint scene seeds split 40/5/5.
- 375 primary targets per condition; 750 LLW / 750 ILW; 750 targets per tier.
- 23,935 total boxes: 14,672 normal; 3,125 rust; 3,095 bulge; 3,043 rust-and-bulge.
- The exact shared asset-pack rust/bulge generators are pinned to asset commit `e4d31c8a323708db4af2f94e4396ca4872457eff`. IDs, patterns, tint, lighting and viewpoints are randomized independently; requested azimuths span approximately ±60°. Actual accepted poses are in the manifest.
- Ten RTX PRO 6000 Blackwell worker jobs; Modal initially allocated eight and queued two. Each worker reused one Isaac process for five scenes. The independent warm pilot renderer was left running.
- Successful dataset run through final packaging: 21 min 13 s, including queueing and replacing a slow serial packager. The final parallel packaging pass took 38.3 s. Per-worker native render/generation time was 6.6–7.9 min.
- Nano and small trained concurrently on one RTX PRO 6000 each: 50 epochs, input 384, batch 64, AdamW, pretrained YOLO26 weights, seed 42. Best validation fitness selected each checkpoint; test data was used for final evaluation.
- Warm timing is a local `model.predict` pipeline measurement on RTX PRO 6000, excluding HTTP latency/cold start. The ~0.1 ms median difference is too small to treat as a meaningful speed advantage.

## Artifacts

`detector-data:/datasets/canis_conditions_1500_20261108T043410Z/` contains the portable `dataset.zip`, unzipped `release/`, source shards, summaries and `timing.json`. ZIP SHA-256: `c5720c4bc323febfb55be5b90fe08279f8ca81e63938e0a386405372c63b7099`.

`detector-models:/condition_v2/compare_20261108T043410Z/yolo26n/` and `yolo26s/` retain best/last checkpoints, training logs/curves, full metrics, confusion matrices, held-out predictions and error overlays. `api_checks.json` records authenticated live-vs-offline checks. `active.json` at `/condition_v2/` selects small.

See [LATEST_MODEL.md](LATEST_MODEL.md) for the latest experimental and retained previous endpoints, and [API_USAGE.md](API_USAGE.md) for their shared response contract.
