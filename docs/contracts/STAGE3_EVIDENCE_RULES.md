# Stage 3 evidence, validity and priority rules

Claude Code, prompt v1.2.1. These are synthetic demonstration rules, not site rules. Codex reviews them at REALITY CHECK 3.2.

| Module | What it decides |
| --- | --- |
| `perception/evidence.py` | 10 evidence kinds, each with its source, scope (drum or area), the hypotheses it supports, and what it **cannot establish**. Findings count distinct views, not frames. A suspected release needs wet/residue evidence plus an independent channel (a swab or a dose change). Condition statuses have no "safe" value. |
| `perception/validity.py` | Each sensor message is classified as fresh, stale, future, saturated (a lower bound), below detection limit (an upper bound), failed, calibration expired, warming up, or invalid. Synthetic maximum ages apply per kind. A hydrogen absence claim is refused when the sensor sits below the region in question, measures headspace, or isn't usable. |
| `perception/priority.py` | A 0–100 **ranking** (`not_a_probability: true`) built from severity (0–45), uncertainty (0–25), recency (0–15), safety (0–15) and exposure cost (−15–0), with a written explanation. Undrawn surfaces raise priority; they never make a drum "fine". |
| `perception/scenario_checks.py` | Checks Codex's scenario files: required fields, case tags, truth kept out of runtime, channel units and hydrogen scope, a cause for every anomaly, a mechanism for every wet case, no scenario raising every channel, consistency between tags and channels, and required case coverage (sound but radioactive, corroded without dose change, hidden condition, healthy control). |

Run: `python perception/scenario_checks.py sim/scenarios/*.json` (exits 1 on any error).
Tests: `perception/tests/test_stage3_rules.py`.
