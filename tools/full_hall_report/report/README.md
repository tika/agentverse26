# C.A.N.I.S. run report

One run folder in; one report out (HTML for screen, A4 PDF for print, `summary.json` for machines). Built only from what the run logged. No model writes a fact into it.

```bash
python tools/full_hall_report/report/build_report.py <run_dir> [--out DIR] [--format auto|framework|canis.v1]
# -> <out>/index.html, <out>/CANIS_report_<run>.pdf, <out>/summary.json, <out>/evidence/
```

Needs Python 3.9+ (Pillow is optional; it shrinks the evidence frames to JPEG) and, for the PDF, Node with Playwright:
`npm install && npx playwright install chromium` in this folder, or set `PLAYWRIGHT_DIR` to any folder whose `node_modules` has it.

**Adding this to your own runs (or asking an agent to):** follow [`IMPLEMENTING.md`](IMPLEMENTING.md). Example output: [`example/`](example/). If the PDF step fails, the HTML and JSON are still written.

## How it is put together

| File | Job | Change it when |
|---|---|---|
| `loaders.py` | Reads a run folder into one run model. Unlogged values stay `None` and print as *not measured*. | A run writes a new log format: add a loader. |
| `rules.py` | Every colour, zone, action and limit, plus the plain-language words. | A rule, a threshold or a source changes. |
| `render.py` | Lays the model and the rule results out as HTML with inline SVG plan and traces. Formatting only. | The layout changes. |
| `style.css` | Design tokens shared with the console: IBM Plex Mono for every label, number, ID and table; IBM Plex Sans for sentences; status colours for status only. | The look changes. |
| `to_pdf.mjs` | A4 PDF with a mono footer (report ID, disclaimer, page n / N). | |
| `assets/` | Dog-head mark, wordmark, Plex fonts (OFL). Embedded, so the report works offline. | |

Input formats:

- **framework**: `memory.json` + `telemetry.jsonl` + `decisions.jsonl` (+ `stills/`, `ground_truth.json`), as in [`docs/report_framework/README.md`](../../../docs/report_framework/README.md). The example run there reproduces `expected_report.md`.
- **canis.v1**: the warehouse-v3 adaptive-aisle takes (`report.json` + `log.jsonl` + `evidence/`). Uses the real evidence frames with the detector's own boxes, the label-reader crops, per-view sensor samples and the Cosmos planner's logged reasons.

## The report, in order

1. **Verdict and actions** (page 1): one-sentence verdict, results bar, eight key numbers, the to-do list (most urgent first), run facts, and what was never measured.
2. **Aisle survey**: plan with 2 m sections, stacks (one cell per shelf), route; section table with peak gamma, H₂, sample count and reason.
3. **Every drum at a glance**: the register, worst first.
4. **Drums that need attention**: per drum, the best evidence frame with the detector box, every other view, the label crop, the readings, why it got its rating, and what to do.
5. **Drums with no problem found**: best view of each, so a clear result has evidence too.
6. **What this report cannot tell you**: uninspected drums and sections, unmeasured sensors, the ground-truth self-check, how ratings are made, limits and sources, the label key.
7. **Appendices**: readings over time with planner decisions marked; the step-by-step record (planner reasons quoted verbatim, with latency); technical details and every evidence frame with its input SHA-256.

The older LaTeX builder (`../pdf/`) is kept for reference.
