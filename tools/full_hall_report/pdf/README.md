# C.A.N.I.S. run report (PDF)

Builds the post-run inspection report from ONE run's logged files. Typeset with LaTeX (Source Sans). Written for store managers and safety staff, not engineers.

```bash
python tools/full_hall_report/pdf/build_pdf_report.py out/full_hall/<RUN_ID> --commit $(git rev-parse --short HEAD)
# -> out/full_hall/<RUN_ID>/report/CANIS_report_<RUN_ID>.pdf
```

Needs `matplotlib`, `Pillow` and a TeX install with `pdflatex` (MacTeX on a Mac; `texlive-latex-extra texlive-fonts-recommended` on Linux).

- Reads only `memory.json`, `telemetry.jsonl`, `decisions.jsonl`, `ground_truth.json` (self-check only), `route.json`, `stills/` and `sim/drums.json`.
- Anything not logged prints as *n/m* (not measured). No language model writes a fact in the report.
- Rules and sources are in `.claude/skills/canis-run-report/SKILL.md`.
- Historical layout preview with older zone labels: [`example/CANIS_report_preview8_014613.pdf`](example/CANIS_report_preview8_014613.pdf).

Aisle ratings are simulation flags. Low gamma records a measurement below the demo threshold. Access decisions require a separate site assessment.
