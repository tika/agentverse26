# Drum detector fine-tuning plan

Status: **execution authorized**. The user requested one YOLO26s distributed run
on eight GPUs and an authenticated inference API. Dataset generation is complete.
The implementation uses one `H100:8` node, global batch 64, 640 px, AdamW,
40 epochs maximum and patience 10. Evaluation and serving use separate L4 workers
after the training node is released. See `docs/yolo26s_training_serving.md` for
commands and the final measured run report.

## Objective and fixed inputs

Fine-tune **one pretrained YOLO26s object detector** (`yolo26s.pt`) for three classes:
`0 drum`, `1 corrosion`, `2 bulge`. Detect physical drums and visible defects in
the simulated robot's RGB frames, then pass detections to the separate agent.
This does not train locomotion, planning, temperature or radiation sensing.

Dataset: `detector-data:/releases/barrels_v2_1200/`, Modal workspace
`paramsachdeva07`, environment `main`. It contains 900 training, 150 validation
and 150 test images at 640×640; 61 scene seeds stay within their assigned splits.
The manifest and all 3,600 image/label/metadata hashes were verified. Do not
resplit nearby views, rewrite the release or mix earlier partial captures into it.

## 1. Build a separate training image and verify labels

- Use a new Modal PyTorch/Ultralytics image, separate from Isaac's bundled Python.
- Pin compatible Ultralytics, PyTorch and CUDA versions. Test the selected GPU
  with an actual forward/backward step; RTX PRO Blackwell needs a compatible
  PyTorch/CUDA build. Successful Isaac rendering does not test PyTorch support.
- Mount `detector-data` read-only for training inputs. Copy the small release to
  local container storage or RAM-cache images after confirming available memory.
- Save outputs to a versioned directory in a separate persistent `detector-models`
  Volume. With distributed training, only the primary rank writes shared artifacts.
- Recheck dataset hashes, class mapping and representative raw/boxed examples.
  Ground-truth JSON, seeds and internal/printed IDs are not model input channels.
- Exercise normal, rust-only, bulge-only and combined examples. Bulged drums have
  overlapping drum/bulge labels: check class-wise learning and postprocessing,
  and associate condition detections with physical drums instead of double-counting
  them. Verify that class-aware filtering retains the required observations.

## 2. Short correctness and timing benchmark

Use the first epochs of the authorized eight-GPU run to check finite losses,
checkpoint persistence and measured timing. Do not start a separate model sweep.

Record image/container build, GPU allocation, dataset caching, first epoch,
steady training epoch, validation, checkpoint and shutdown times separately.
Replace the provisional timing ranges below with measured values before the
full run. A rendering benchmark is not a training benchmark. Do not inspect
test predictions during development or use test scores for checkpoint selection.

## 3. Initial training recipe

- Start from pretrained **`yolo26s.pt` only**. No model-family comparison,
  candidate sweep, repeated-seed search or ensemble is planned.
- Train at native 640 resolution. Enlarging existing 640 images does not recover
  missing image detail. More native pixels/closer views would require new captures.
- Initial cap: 40 epochs, early stopping patience 10, training RNG seed 42.
  Select the best validation checkpoint from this one run.
- Use global batch 64 (eight examples per GPU). Enable mixed precision when its compatibility check
  passes. Save the resolved optimizer, learning rate and every augmentation setting.
- Use mild brightness/contrast and horizontal flips; no vertical flips. Keep hue
  shifts small so corrosion colour remains meaningful. Record one conservative
  augmentation recipe before starting the full run.
- Save `best.pt`, `last.pt`, optimizer state where supported, epoch metrics,
  training plots, confusion matrices and validation predictions. Checkpoints and
  the dataset manifest hash must survive a stopped container.

The pretrained model supplies general visual features. On each training batch,
the loss compares predicted classes/boxes with annotations, and backpropagation
adjusts weights. Validation chooses the checkpoint; it never updates weights.

## 4. How to use 8–10 GPUs

### One model, with optional distributed data parallel (DDP)

There is one YOLO26s training run. The recommended starting hardware is one RTX
PRO 6000. If more GPUs are used, they jointly train this same model through DDP;
they do not train independent candidates or independently trained weight files
that must later be combined. Measure a scaling benefit before paying for a large
GPU allocation. Hardware choice is separate from the now-fixed model choice.

YOLO accepts multiple CUDA device IDs and synchronizes model gradients during
training. Modal documents single-node configurations such as `H100:8`; an
eight-device example uses `device=[0,1,2,3,4,5,6,7]` with a batch divisible by 8.
The eight or ten **independent RTX containers used for rendering are not one
DDP-connected machine**. Do not assume `RTX-PRO-6000:8` availability from the
single-GPU experiment. Check the provider's documented topology first.

A ten-GPU single-model run exceeds the documented eight-GPU single-node layout
and requires a supported multi-node configuration, rendezvous/network setup and
distributed data sampling. Modal supports clustered torchrun training, but this
adds complexity without a clear benefit for this dataset.

With global batch 64, 900 images give about 15 batches per epoch: eight GPUs get
only eight images each per full batch and must synchronize frequently. Raising
the global batch to 512 gives only about two batches per epoch, changing the
optimization schedule and reducing updates. A faster wall clock would not be a
fair quality comparison unless effective batch, update count and schedule are
accounted for. Startup, data loading and validation also limit scaling.

## 5. Provisional time and cost budgets

**These are estimates, not measurements of this dataset's training throughput.**
Assume a small detector, 640 inputs and up to 40 epochs, including ordinary
startup/caching/validation overhead. Initial dependency-image builds, queueing,
failed runs and TensorRT export can add time. Early stopping can reduce it.

| Configuration | Estimated wall time | GPU-only cost for that time |
| --- | --- | --- |
| 1 RTX PRO 6000, YOLO26s | 10–25 min | $0.51–$1.26 |
| 1 H100, YOLO26s | 8–20 min | $0.53–$1.32 |
| 2 H100, same YOLO26s via DDP | 6–15 min | $0.79–$1.97 |
| 8 H100, same YOLO26s via DDP | 5–20 min; may not beat a smaller setup | $2.63–$10.53 |

Actual cost is the sum of allocated workers' active time. CPU, RAM, storage,
network, tax and credits are separate. There is no multi-candidate sweep budget.

Published standard GPU rates checked 7 November 2026: RTX PRO 6000
$0.000842/s ($3.0312/h), H100 $0.001097/s ($3.9492/h). These rates and the
hardware's speed do not establish an eightfold training speedup.

## 6. Checkpoint selection and operating thresholds

Use validation-only metrics: per-class precision/recall, mAP50, mAP50–95,
false alarms per image and fault association per drum. Stratify tiny vs larger
rust boxes, close vs context views, occlusion and drum count. Overall box totals
are dominated by rust patches, so explicitly examine bulge recall too.

Keep YOLO26s fixed and report fault-recall/false-alarm targets that cannot be
achieved. Select per-class suspect/confirm
thresholds from validation data: suspects trigger another viewpoint or depth
check; higher-confidence findings become reports. Confidence is not gas pressure.
If uncertainty is quantified, resample scene groups rather than pretending nearby
views from the same scene are independent observations.

## 7. Final test, export and serving handoff

- Freeze the best YOLO26s checkpoint and thresholds, then evaluate once on the 150 test
  images. Save missed defects, false alarms and results by view/box size.
- Test performance is synthetic studio performance. Actual hall backgrounds,
  stainless ILW drums and real cameras require separate evaluation; this dataset
  covers the approved painted LLW assets.
- Store a versioned bundle under `detector-models:/runs/RUN_ID/`, including
  weights, class map, preprocessing, thresholds, training config, software versions,
  source/dataset hashes, metrics and plots. Never put large model weights in Git.
- Optional later optimization: export the trained YOLO26s to ONNX and TensorRT FP16. Build the engine for the eventual
  deployment GPU/runtime; a training H100 engine should not be treated as a portable
  RTX/L4 engine. Verify prediction/metric parity and actual inference latency.
- The robot receives boxes/classes/confidences plus frame timestamps. It uses
  separate depth/temperature/radiation observations and planning logic to act.
- Deploy an authenticated Modal HTTPS endpoint on an L4, with zero minimum
  containers and an idle timeout. Serve the pinned best PyTorch checkpoint;
  engine export is optional follow-up work. Keep Isaac's Python clean.

## Progress and reproducibility requirements

Track run state, epoch/target, epoch seconds, losses, validation metrics,
best epoch and checkpoint location. Provide measured ETA after warm-up, not
simulator timing. Persist progress/checkpoints after each epoch. Set timeouts and
release only this task's workers. A restart must resume the same model/configuration
and preserve existing checkpoints.

## Official references

- [YOLO training and multi-GPU usage](https://docs.ultralytics.com/modes/train/)
- [YOLO26 model family](https://docs.ultralytics.com/models/yolo26/)
- [Modal GPU configurations](https://modal.com/docs/guide/gpu)
- [Modal multi-node torchrun](https://modal.com/docs/guide/multi-node-training)
- [Modal pricing](https://modal.com/pricing)
- [TensorRT export and compatibility](https://docs.ultralytics.com/integrations/tensorrt/)
