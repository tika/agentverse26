# Does Cosmos improve a Spot inspection?

**Status** Draft preregistration. Agree on the scoring rules, practical effect, sample size and exclusions before opening the final test set.

## What we want to find out

Can Cosmos help Spot make better inspection decisions under the same time and safety constraints as a well-built rules planner? Run both planners with the same sensors, perception outputs, map, locomotion, candidate actions and safety supervisor. Give both the same recent readings and history summaries. The supervisor can veto any action from any arm.

| Arm | What chooses the next action |
| --- | --- |
| Route patrol | An industry-style proxy that visits ordered waypoints, navigates around obstructions when possible and logs alerts. It can use the shared safety supervisor and local navigation. |
| Adaptive rules | A deterministic planner that uses persistence and rate of change, cross-checks sensors, tracks uncertain findings, and chooses a safe alternate view, repeat sample, detour or escalation. Give it the same action options as Cosmos. |
| Cosmos | A frozen checkpoint and prompt that rank the same actions using the same structured evidence. Use the shared rules fallback on invalid output or timeout and count the run under Cosmos. |
| Human operator | A person chooses from the same actions on the same evidence dashboard. Run this as a separate study with the same robot and supervisor. |

The primary comparison is **Cosmos versus adaptive rules**. The route patrol answers whether adaptive inspection helps at all. Boston Dynamics documents local rerouting in [Autowalk Directed Exploration](https://dev.bostondynamics.com/docs/concepts/autonomy/directed_exploration.html). A result against our proxy applies to that implementation. A product-level comparison requires running the commercial system under matched conditions.

For the first study, give both planners the same structured detector outputs. Test raw RGB crops as a separate Cosmos variant. The current demo passes Cosmos RGB and uses simulator segmentation as a corrosion detector stand-in. The existing Cosmos on/off switch is a starting point for the harness. The matched input mode and a credible adaptive rules baseline still need to be built and verified.

## Three scenario families

| Family | Hard case | Lookalike control |
| --- | --- | --- |
| Source attribution | A gamma gradient crosses an aisle and peaks near the wrong drum from the first vantage point. A safe second view can resolve the source. | Elevated background or a source beyond the target area. Report the measured field without assigning it to a drum. |
| Conflicting evidence | A warm drum intermittently vents gas. The highest point reading is displaced from the vent and a nearby drum looks more damaged. | A warm neighbour with no persistent gas signal, or cosmetic rust. Grade the follow-up and the strength of the claim. |
| Change mid-run | A wet patch appears across a planned route near multiple drums. Depth offers a safe detour and another view can narrow the candidates. | A reflective dry floor, or a real puddle whose source remains unresolvable. Grade route choice separately from drum attribution. |

Have a teammate who did not tune either planner author held-out variants and adjudicate the rubric before testing. Vary layout, fault location, visibility, noise, event timing and whether a safe follow-up exists. Include clean or lookalike cases so an agent cannot win by always escalating. Start with 50 independently generated cases per family, including 15 controls per family. Adjust the total from the pilot and then lock the mix. Each case gets one paired run, with the same initial state, time-based event schedule and seeded noise field. Each robot samples that field from its own trajectory. Randomize arm order and reset the simulation and planner state between runs.

Keep the test layouts, scenario templates and assets out of detector training, LoRA examples, prompt tuning and baseline tuning. Hold out families of visual assets as well as layout seeds where practical. Export observations and action logs separately from simulator truth. The scorer can see truth. The planners and operators get only the mission brief, their observations and shared derived evidence. Audit the payloads for leaked drum IDs, defect labels and event flags. Use an independent replay or alternate noise and rendering setup to probe simulator shortcuts. Treat these as robustness checks with their own reported results.

## What counts as a win

A mission passes if it follows the shared safety envelope, finishes within the predeclared simulated time budget, and produces the right inspection disposition. A disposition names the affected area or drum when evidence supports it and takes the appropriate follow-up or escalation. It also avoids unsupported attribution or an alert on a clean case. An unresolved report can pass when the rubric establishes that no safe informative follow-up exists. Predeclare thresholds and budgets using the inspection source register and the development pilot. Score observable decisions, samples and motion from logs. Keep any judgement calls blinded to arm identity.

Report alongside the pass rate:

- Safety events, attempted unsafe actions caught by the supervisor, and time spent near limits.
- Missed hazards and false alerts, broken down by family and control cases.
- Time to disposition, distance walked, samples taken, and end-to-end decision latency at p50 and p95 on the same hardware.
- Cosmos timeouts, invalid outputs and fallback rate. Include these runs in the primary analysis.

A timeout or planner failure counts as a mission failure. Define infrastructure failures before testing and rerun the full pair only for documented infrastructure failures. Retain the original logs. Use a scenario-level pass/fail as the primary endpoint so frames, drums and decisions within one mission never inflate the sample size.

## Sample size and decision rule

Use a **two-sided exact McNemar test at α = 0.05** for the primary paired pass/fail comparison. Report both discordant counts, both pass rates and the paired absolute difference with a 95% confidence interval. For independent cases, estimate the interval by resampling paired cases within each family and combining them at the locked family weights. If layouts are reused, use layout as the analysis cluster and recalculate power. [McNemar test reference](https://www.ncbi.nlm.nih.gov/books/NBK560699/)

With 150 independent pairs, power is about **86%** if Cosmos alone passes 25% of cases and rules alone passes 10%. That is a 15 percentage point lift with 35% discordance. For a 10-point lift with 20% Cosmos-only wins and 10% rules-only wins, **270 pairs** give about **83%** power. These are planning assumptions. Use 20–30 separate development cases to estimate discordance, sanity-check the rubric and measure runtime. Choose the smallest worthwhile effect as a team and lock the final sample size before evaluating held-out cases. [Paired exact power reference](https://search.r-project.org/CRAN/refmans/Exact/html/power.paired.test.html)

A provisional benchmark for a useful result is an observed lift of at least 10 points, a confidence interval above zero, and compliance with the predeclared safety and latency limits. That supports a positive effect and an observed lift of practical interest. To claim the true lift exceeds 10 points, require the interval's lower bound to exceed 10 points and power the study for that claim. Report an inconclusive result when the interval is too wide. Treat secondary comparisons as exploratory, or specify a multiple-testing procedure such as Holm's before testing.

## Human comparison and execution

Start with 8–12 operators as a descriptive pilot. Give everyone the same training, interface and mission time budget. Counterbalance scenario order and assign matched cases across operators. Each person sees a case once to reduce memory effects. Run the robot arms on those same assigned cases for comparison. Report operator experience and separate novice results from any inspection specialists. Power a larger study using the variation across participants and scenarios, and account for both in the analysis. [Crossover trial design guidance](https://www.bmj.com/content/366/bmj.l4378.short)

Run the development pilot on the warm Isaac worker. Save machine-readable logs for every run and record video only for debugging and representative examples. Record wall-clock reset, simulation and inference time separately. Replay identical logged observations for fast decision-only debugging. Use closed-loop runs for the actual comparison because decisions change what the robot sees next.

Run the first pass with the shared segmentation stand-in if needed to isolate the decision layer. Repeat the comparison with the frozen RGB detector and realistic sensor noise before making an end-to-end claim. A positive result supports the scenarios and sensing conditions tested. Extending the claim to a nuclear store requires independent evidence with representative sensors, procedures and operators.
