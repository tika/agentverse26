# Warehouse inspection display

Use the printed package ID and tier to connect the active target, the camera evidence, the run ledger and the operator map.

| Moment | Camera | Map |
| --- | --- | --- |
| Approach, turn and settle | Show the selected package and movement phase. Show a box only when there is a matching detection on this frame. | Highlight the active route and target. |
| Inspecting | Draw outline boxes with a text label and confidence. Use blue for package/ID, orange for corrosion and violet for bulge. | Highlight the active package and tier. |
| Assessment recorded | Draw an opaque green, yellow or red result shape over the assessed package on a separate result layer. Include package ID and a text label. Keep a raw evidence view available. | Draw the same result color for the same package and tier. |
| Unseen | Leave the result layer empty. | Keep the package neutral. |

Result meanings:

- **Green, OK in inspected views.** The required observations passed and yielded no visible finding. An empty detector response or incomplete coverage cannot produce green.
- **Yellow, unsure.** Identity, visibility or evidence is insufficient, or a candidate finding needs a second view. Record the reason and schedule a revisit when possible.
- **Red, defect finding.** Accepted evidence supports visible corrosion, bulging or both. Keep the type and supporting frame references alongside the result.

Use one assessment record for both the overlay and map. Include the run ID, printed package ID, tier, status, reason, evidence frame IDs and model checkpoint hash. Keep visual coverage separate from condition. A result shape belongs only on a frame where the package is associated or projected with valid geometry. The raw image and detector response remain available for review.

First acceptance case: Spot approaches one package, turns, holds, captures, and shows the correct active box. After assessment, the camera result layer and map update together for that package. Replay the same evidence to verify it neither increments coverage nor marks a neighboring package.
