> **Invented example.** This shows what each section should contain, built from the invented files in [`run/`](run/). In a real report the sections are typeset as a PDF following [the framework](../README.md).

# C.A.N.I.S. Drum Store Inspection Report

| | | | |
|---|---|---|---|
| Store | Example store, aisle E (invented) | Report number | CANIS-example |
| Inspected on | 2000-01-01 00:00:00 UTC | Time taken | 1 min 20 s |
| Inspected by | C.A.N.I.S. inspection robot | Status | Invented example |

## Summary

| Item | Count | Item | Count |
|---|---|---|---|
| Drums checked | 5 of 6 | Areas safe to enter | 1 |
| Need action | 2 | Areas restricted | 1 |
| Check again | 2 | Areas to keep out of | 1 |
| No problem found | 2 | Areas not checked | 1 |
| Radiation dose to the robot | 0.251 of 5.0 µSv (5%) | Time taken | 1 min 20 s |

**2 drums need action and 2 should be checked again. 1 area must be kept clear of people. 1 area is restricted. 1 area was not checked.**

## 1. Who can go where

The aisle plan goes here: drums, 2 m zones and the robot's route.

| Section | Rating | Why |
|---|---|---|
| 4–6 m | Keep out | Radiation reached 120 µSv/h, above the keep-out level. |
| 0–2 m | Restricted | Damaged drum here: E-L-01-T2. |
| 2–4 m | Safe | Radiation stayed normal (highest 3.1 µSv/h). |
| 6–8 m | Not checked | The robot did not go here this time. |

## 2. Every drum at a glance

| Drum | Waste | Side | Shelf | Result | What was seen | How sure |
|---|---|---|---|---|---|---|
| E-L-01-T2 | Low-level | Left, stack 1 | Middle | Action needed | Rust | High (91%) |
| E-L-02-T1 | Intermediate-level | Left, stack 2 | Bottom | Action needed | Bulging | High (88%) |
| E-R-01-T3 | Low-level | Right, stack 1 | Top | Check again | Rust | Medium (62%) |
| E-R-02-T1 | Intermediate-level | Right, stack 2 | Bottom | Check again | Nothing found | -- |
| E-L-01-T1 | Low-level | Left, stack 1 | Bottom | No problem found | Nothing found | High (95%) |
| E-R-01-T1 | Low-level | Right, stack 1 | Bottom | No problem found | Nothing found | High (93%) |

This is the first inspection of these drums, so there is nothing to compare with yet. Not measured in this inspection: drum surface temperature, hydrogen gas and surface wipe (swab) results.

## 3. Drums that need attention

The evidence photo goes at the top of each block. This invented run has none, so each block prints "photo not logged".

### Drum E-L-01-T2: Action needed

Low-level waste | Aisle E, left side, stack 1, middle shelf

| | |
|---|---|
| Photo | photo not logged |
| What was seen | Rust |
| How sure | High (91%) |
| Why this rating | Rust seen in 3 of 3 camera views. |
| Radiation at drum | Normal (1.5 µSv/h) |
| Surface wipe (swab) | Not taken |
| Surface temperature | Not measured |
| What the robot did | 0:17 Rust seen in 3 of 3 views (how sure: 91%). Action needed. |

**What to do:** Ask an engineer to assess how far the rust has gone. Take a surface wipe if none was taken. Consider placing the drum in an overpack (a larger outer drum).

### Drum E-L-02-T1: Action needed

Intermediate-level waste | Aisle E, left side, stack 2, bottom shelf

| | |
|---|---|
| Photo | photo not logged |
| What was seen | Bulging |
| How sure | High (88%) |
| Why this rating | Bulging seen in 2 of 3 camera views. |
| Radiation at drum | Raised (14 µSv/h) |
| Surface wipe (swab) | Not taken |
| Surface temperature | Not measured |
| What the robot did | 0:52 Bulging seen in 2 of 3 views (how sure: 88%). Action needed. |

**What to do:** Limit access to this aisle. Ask an engineer to assess the drum for pressure build-up, and measure its surface temperature (not measured in this inspection).

### Drum E-R-01-T3: Check again

Low-level waste | Aisle E, right side, stack 1, top shelf

| | |
|---|---|
| Photo | photo not logged |
| What was seen | Rust |
| How sure | Medium (62%) |
| Why this rating | Possible rust seen in 3 of 8 camera views; the rest looked normal. |
| Radiation at drum | Normal (1.7 µSv/h) |
| Surface wipe (swab) | Not taken |
| Surface temperature | Not measured |
| What the robot did | 0:27 Top shelf: the camera sees it at a steep angle, so the robot always takes a closer look (1 of 3 first views showed possible damage). 0:33 Mixed result: possible damage in 3 of 8 views. Marked to check again. |

**What to do:** Inspect again within 7 days, with a closer look and a surface wipe (swab).

### Drum E-R-02-T1: Check again

Intermediate-level waste | Aisle E, right side, stack 2, bottom shelf

| | |
|---|---|
| Photo | photo not logged |
| What was seen | Nothing found: the robot got no clear view |
| How sure | -- |
| Why this rating | The robot could not get a clear look. |
| Radiation at drum | Not measured |
| Surface wipe (swab) | Not taken |
| Surface temperature | Not measured |
| What the robot did | 1:01 Radiation rose sharply (120 µSv/h). The robot backed away. 1:06 No clear view before backing away. Could not inspect. |

**What to do:** Inspect again once the area is clear and radiation is back to normal.

## 4. What was not checked

- E-R-02-T1 was not inspected: radiation rose sharply before the robot got a clear view.
- The 6–8 m section was not reached.
- Drum surface temperature and hydrogen gas were not measured anywhere on this round, and no surface wipes were taken.

## 5. How accurate was the robot?

This is a simulated store, so we know which drums were really damaged. The robot was not told.

- It flagged 2 of the 4 damaged drums.
- It missed 1 damaged drum: E-R-01-T1 (rust 0.4).
- It could not inspect 1 damaged drum: E-R-02-T1 (rust 0.3).
- It raised 1 false alarm: E-R-01-T3 was actually undamaged.

## 6. How this report was made

Describe the method in plain words and print the limits table from [section 4 of the framework](../README.md#4-from-data-to-verdicts). Finish with a short "Please note" paragraph: this was a simulated store, the detector was trained on computer-generated images, rust extent is estimated from photos, and only a surface wipe can show contamination.

## Appendix A. The robot's route over time

The chart of distance along the aisle against time goes here, with each verdict marked.

## Appendix B. Step-by-step record

| Time | Drum | What happened |
|---|---|---|
| 0:12 | E-L-01-T1 | No damage seen (3 of 3 views looked normal). No problem found. |
| 0:17 | E-L-01-T2 | Rust seen in 3 of 3 views (how sure: 91%). Action needed. |
| 0:22 | E-R-01-T1 | No damage seen (3 of 3 views looked normal). No problem found. |
| 0:27 | E-R-01-T3 | Top shelf: the robot always takes a closer look (1 of 3 first views showed possible damage). |
| 0:33 | E-R-01-T3 | Mixed result: possible damage in 3 of 8 views. Marked to check again. |
| 0:52 | E-L-02-T1 | Bulging seen in 2 of 3 views (how sure: 88%). Action needed. |
| 1:01 | E-R-02-T1 | Radiation rose sharply (120 µSv/h). The robot backed away. |
| 1:06 | E-R-02-T1 | No clear view before backing away. Could not inspect. |

## Appendix C. Technical details

| | |
|---|---|
| Damage detector | example-detector (invented) |
| Detector calls | 20 (0 failed) |
| Decision rule | Side look, 3 views: fault in >=2 -> defect; normal in >=2 and no fault -> OK; otherwise, and always for tier 3, a closer look (8 views in total). |
| Written explanations | None |
| Logged channels | Robot pose, camera tilt, radiation, decisions. No temperature, gas or swab. |
| Status names | Action needed = `Confirmed defect`; Check again = `Suspect` or `Couldn't inspect`; No problem found = `OK` |
