# Warehouse-v3 visual recheck sensitivity analysis

This analysis runs 2,000 paired simulated walks over 420 visible barrel faces in seven mapped aisles. The planned route is 164.6 m. The fixed policy takes one view per barrel. The adaptive policy takes two more views when the first view is uncertain and records a verdict only if the two confident predictions agree. Both policies get the same barrel conditions and first views.

The expanded checkpoint's saved held-out report gives primary-target condition accuracy by group. The pooled inputs here are 163/165 for yellow LLW and 70/100 for metallic or blue-teal ILW. It does not give the per-class prediction and confidence records needed to simulate the inspection rule directly. This run therefore uses those aggregate accuracies and sweeps assumed uncertain-view rates of 10%, 25% and 40%. It assumes the same accuracy across classes within a category and distributes errors uniformly across the other classes. The synthetic fault mix is 70% normal, 15% rust, 10% bulge and 5% both.

At a 25% assumed uncertain-view rate:

| Outcome per walk | Fixed | Independent rechecks | Half the cases repeat the first view | All rechecks repeat the first view |
|---|---:|---:|---:|---:|
| Drums left for review | 105.0 | 52.8 | 78.8 | 105.0 |
| Faulty drums with the correct condition | 69.7% | 82.1% | 76.0% | 69.7% |
| Faulty drums classified as normal | 2.19 | 2.22 | 2.21 | 2.19 |
| Clean drums flagged | 15.41 | 15.67 | 15.54 | 15.41 |
| Mission duration | 73.4 min | 143.4 min | 143.4 min | 143.4 min |

The independent scenario left 52.2 fewer drums for review per walk (paired bootstrap 95% interval 51.9–52.5 fewer). The half-repeat scenario left 26.2 fewer (26.0–26.4 fewer). These intervals capture simulation sampling error under the assumptions. They do not account for uncertainty in those assumptions.

The paired bootstrap resamples whole walks 10,000 times. Correct fault classification increased by 12.37 percentage points (95% interval 12.24–12.50) with independent views, or 6.25 points (6.16–6.35) in the half-repeat scenario.

The pooled simulated McNemar comparison counts 31,097 faulty drums classified correctly only with independent rechecks and zero correctly classified only with the fixed policy. The half-repeat counts are 15,717 and zero. The policy preserves existing confident verdicts, so these disagreements can only go one way. The pooled test is descriptive. Use the walk bootstrap for uncertainty because it keeps drums within each walk together. There are zero discordant pairs when all rechecks repeat the first observation.

The expanded and previous detectors each classified 233 of 265 held-out synthetic primary targets correctly at the reported operating point (87.9%). These totals do not reveal how often one model was right and the other wrong. A detector-level McNemar test needs the paired predictions for those images.

The baseline assumes 0.8 m/s walking speed and a ten-second first look at each drum. The adaptive model adds twenty seconds per extra look at the same stop. These are modeled mission times and can differ from the physical posture demo. This evaluation covers visual triage. Dose, route disruptions, and hardware outcomes require separate evaluation.

Run the sensitivity analysis:

```sh
uv run --no-project --with numpy --with scipy python eval/warehouse_policy_eval.py
```

To use measured per-class observations, supply the expanded checkpoint's original held-out `evaluation/test_predictions.json` from the training run. The script uses the class and confidence attached to each primary target and records the input file hash. Verify that the prediction file came from the expanded checkpoint before quoting its results.

```sh
uv run --no-project --with numpy --with scipy python eval/warehouse_policy_eval.py \
  --predictions /path/to/test_predictions.json \
  --out eval/results/warehouse_v3_measured_summary.json
```
