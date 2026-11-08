# CANIS evaluation

*As of 8 Nov 2026. Detector: YOLO26s (run `compare_colors_20261108T053740Z_continued`), cut-off 0.25. 2,000 paired simulated walks, seed 20261108.*

**Same robot, same detector, different decisions.** CANIS finds the same faulty drums as a fixed-route robot (87.6% vs 87.8%). It settles **2.6 percentage points more of them itself** (95% range 2.3 to 2.8) and leaves **87% fewer drums for a person to check** (95% range 83% to 91%). McNemar's test confirms the difference isn't luck.

## What we compared

Both robots have the same body, camera and detector, and walk the same pretend versions of our 36-drum aisle. Only their decisions differ.

| | Fixed-route robot (Autowalk-style) | CANIS |
|---|---|---|
| Route | Fixed, recorded | Same start, changes plan |
| Photos per drum | 1 | 1, plus up to 2 more if unsure |
| If unsure about a drum | Leaves it for a person | Looks again; leaves it for a person only if still unsure |
| Blocked aisle | Walks round it | Walks round it |
| Radiation spike | Walks through it | Backs off, comes back later, keeps to a dose budget |

The fixed-route robot copies how today's inspection robots work, from public descriptions: a route recorded by a person and replayed, with set actions at each stop.

## Where the numbers come from

- **Measured:** the detector's results on 265 photos it had never seen. At confidence 0.25 it classified 233 of 265 drums correctly (87.9%), and that rate is used for both rust and bulges. The first looks in the final showcase run give the rest: 1 of the 19 rusty views it flagged scored between 0.25 and 0.5, which counts as "unsure". Of 75 clean drum views, it flagged 2 as unsure rust (2.7%) and 1 as a bulge (1.3%). The layout (the 36 drums on aisle A from the final showcase run) comes from `sim/warehouse-v3/map.json`.
- **Simulated:** a fast Python simulation (`eval/canis_eval.py`) walks both robots through 2,000 random versions of the hall. At each drum, a random draw using the measured rates decides what the detector "saw": sure, unsure or nothing. Both robots get the same draws, so the comparison is fair.
- **Assumed (our settings):** each drum has a 30% chance of being faulty (35% of those are bulges), a radiation spike happens in half the walks, an aisle is blocked in 30% of walks, and dose is in simulated units, not mSv. Only the 36 inspected drums give off radiation in the model.

## Test 1: 95% ranges (paired bootstrap)

Each number is an average over 2,000 walks. To see how much it could move by chance, we re-drew our own walks at random with replacement 10,000 times and kept the middle 95% of the answers. **If the range of the difference doesn't include zero, the difference is real.**

![Defects found and settled](results/defects.png)

| Per walk, average | Fixed-route | CANIS | Difference (95% range) | Real difference? |
|---|---|---|---|---|
| Faulty drums found | 87.8% | 87.6% | −0.3 points (−0.4 to −0.2) | About the same: same detector |
| Faulty drums settled by the robot | 85.0% | **87.5%** | **+2.6 points (2.3 to 2.8)** | Yes, CANIS better |
| Drums left for a person to check | 0.96 | **0.12** | **−87% (83% to 91% fewer)** | Yes, CANIS better |
| Walks over the dose budget | 26.8% | **0.7%** | −26.1 points (−28.0 to −24.2) | Yes, CANIS better |
| Robot dose (simulated units) | 9.09 | **2.45** | −6.64 (−7.19 to −6.11) | Yes, CANIS better |
| Mission time (minutes) | 6.4 | 9.3 | +2.9 (2.7 to 3.0) | Yes, CANIS slower (the trade-off) |

![Drums left for a person](results/human_entries.png)

## Test 2: McNemar's test

McNemar's test compares two robots drum by drum. Across all walks there were 21,711 faulty drums. For each one: **did each robot settle it itself?** Drums where both gave the same answer tell us nothing, so the test looks only at the two "disagree" boxes. If the robots were equally good, those two boxes would be about the same size.

| | CANIS settled it | CANIS didn't |
|---|---|---|
| **Fixed-route settled it** | 18,400 | 47 |
| **Fixed-route didn't** | **601** | 2,663 |

The disagree boxes are **601 vs 47**. A split that lopsided would almost never happen by chance (p < 0.001). CANIS settles drums the fixed-route robot can't.

The same test on drums *found* shows a small gap the other way. The fixed-route robot found 55 drums CANIS didn't, and CANIS found none it missed (about 0.03 per walk). CANIS stopped short of 47 of them to keep within its dose budget, reporting them as "Couldn't inspect". It called the other 8 OK after two clear extra looks.

## Limits

- **Simulation.** Only the detector results and the hall layout are measured.
- **Synthetic test photos.** The detector was tested on synthetic photos of drums, not real ones.
- **Drums, not trips.** "Drums left for a person" counts drums, and one person could check several in one trip.
- **Second looks.** Each second look is treated as a fresh draw. Real second looks may be less independent.
- **Dose units.** Dose is in simulated units.
- **Not yet done:** running both robots in Isaac Sim to check the simulation.

## Reproduce

```bash
python -m pip install numpy scipy pandas matplotlib
python eval/canis_eval.py --walks 2000 --boot 10000 --seed 20261108
python eval/make_charts.py
```
