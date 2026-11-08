# Reproduce the expanded-color YOLO26s experiment

To use the deployed model, follow [LATEST_MODEL.md](LATEST_MODEL.md). No
rendering, training or redeployment is required for API clients. The commands
below launch billable GPU work only when explicitly run.

## Assets and persisted data

From updated `main`, extract the pinned shared warehouse asset pack:

```sh
mkdir -p .runtime/drum-pilot15-assets
python3 -m zipfile -e handoff/CANIS_YOLO_DRUM_ASSETS_FOUR_CONDITIONS_V1.zip \
  .runtime/drum-pilot15-assets
```

`color_expansion.py` uses that warehouse's LLW and blue-teal ILW profiles and
fault generators. The separate blue-painted LLW studio pilot is excluded.
The original 1,500-image dataset must exist in `detector-data` at
`/datasets/canis_conditions_1500_20261108T043410Z/dataset.zip`. Rendering and
training use the active Modal workspace; another workspace does not
automatically have the owner's Volumes or weights.

## Generate the additional 1,000 frames

```sh
python3 detector/v2/color_expansion.py yellow
python3 detector/v2/color_expansion.py ilw
```

Each command submits five independent RTX PRO 6000 jobs. Yellow generates
750 frames from 25 seeds; ILW generates 250 frames from ten seeds. Each worker
reuses Isaac across its assigned seeds. Requested angles span ±60 degrees;
IDs, viewpoints, rust, bulge amplitude and lighting are seeded independently
of the condition labels. Targets are tiers 1–2.

The first command creates ignored `.runtime/color_expansion.json`; the second
extends its call list. Preserve this pointer while the run is active. Reusing
a completed pointer can resubmit work, so retain completed pointers separately
before starting a genuinely new experiment. Modal Dict
`canis-color-expansion-progress` stores per-shard progress.

## Assemble, compare, then continue from the previous weights

```sh
python3 detector/v2/color_train_pipeline.py
python3 detector/v2/color_train_pipeline.py continue
```

The first command waits for all ten shards, combines them with the retained
1,500 images, verifies labels and disjoint seeds, writes a shuffled `train.txt`,
then reproduces the initial 50-epoch small-model experiment and matched old
checkpoint comparison. The second command reproduces the selected 20-epoch,
learning-rate 0.0001 continuation from the previous trained best checkpoint.
Each trainer uses one RTX PRO 6000. The initial expanded-data experiment was
weaker; both attempts remain archived. Validation selected the continuation;
the test set was not used to choose between candidates.

Assembly retains original split assignments. Totals are 2,500 images,
2,000 train / 235 validation / 265 test, and 1,500 yellow + 1,000 blue-teal
ILW primary targets. The original release used a capped selection from early
ILW capture shards; `selected_manifest.json` records that selection. New runs
directly request the final 250 additional ILW frames. They reproduce the recipe
and split policy, not a byte-identical initial capture/selection history.

If comparison alone failed after training, reuse the saved weights with
`python3 detector/v2/color_train_pipeline.py compare`; do not regenerate data.
Model progress is in Modal Dict `canis-color-training-progress`. Results download
to ignored `out/color_expansion/RUN_ID/`; data and checkpoints persist in the
volume paths listed in the latest-model handoff.

## Serve separately

For the existing saved continuation in the owner's workspace:

```sh
CANIS_MODEL_SCALE=s \
CANIS_COMPARISON_ID=compare_colors_20261108T053740Z_continued \
CANIS_API_APP=canis-yolo26s-expanded \
  python3 -m modal deploy detector/v2/serve.py
```

For a new run, substitute its evaluated comparison ID and use a distinct app
name. `CANIS_API_APP` is passed into the serving image as well as the local
declaration. Bare `modal deploy detector/v2/serve.py` still targets the previous
default app/checkpoint. Never redeploy an experimental checkpoint under the
previous production app name by accident. Verify `/health`, `best_sha256` and
the shared four-condition response contract before integration.
