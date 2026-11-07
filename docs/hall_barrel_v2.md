# Reviewed barrel design in the 28-drum hall

The hall now uses the reviewed LLW appearance from `docs/barrel_design_handoff.md`
and `sim/render_barrel_preview.py`. The prior screenshots showed the older
`defects.py` raised-patch system; that is no longer used on painted LLW drums.

The **28 positions, yaw angles, stable IDs, printed IDs, category assignments and
paint-colour assignments are preserved**. There are 16 painted 208 L LLW drums
and 12 larger stainless 500 L ILW drums. ILW retains its category-specific geometry,
stainless material and corrosion treatment; the LLW fixture is not stretched onto it.

The three reviewed examples in the actual hall are:

| Plate | Internal ID | Shape | Rust |
|---|---|---|---|
| A03 | D03 | Nominal 0.598 m OD, 0.88 m height | Thin chipped oxide |
| B01 | D05 | Swollen body and domed lid | None; aged paint only |
| C02 | D10 | Same swelling and dome as B01 | Thin chipped oxide |

The reviewed 8% peak local radial field produces approximately 0.630223 m maximum
diameter. The lid centre rises 70 mm above its original recessed surface to
0.935 m. Bungs and the curved warning plate follow the new shape. This is authored
visual geometry; it does not establish internal pressure, gas composition or shell
strength. Rust and bulge remain independently switchable.

Paint uses the same fine ageing as the reviewed preview, with the hall's existing
yellow/grey/blue palette. Oxide is a separate masked mesh 0.35 mm above the body,
with dark brown/red-brown chips, restrained orange edges, hoop/chime concentration
and sparse streaks. It follows the nominal or swollen profile. Each drum has its
own oxide material so one drum's seed cannot overwrite another's. The denser
failure region faces the aisle; body yaw and plate orientation are preserved.

`barrel_appearance.py` is shared by normal hall construction and state changes.
`set_drum_state('D05', 'bulge')`, `'clean'`, `'rust'` and `'rust+bulge'` rebuild
the body consistently. State resets remove old shape/fault geometry. Existing
release fixtures remain in inventory, but are hidden in the static solid-waste
review, as in the live agent's existing presentation policy.

## Reproduce static screenshots

```sh
python3 -m unittest discover -s sim/tests -v
python3 tools/run_hall_barrel_review.py
```

This uses one RTX PRO 6000 (L40S/L4 fallback), Isaac Sim 6.2, and the verified
headless real-time renderer. It captures **static pictures only**; no robot
mission, incident rollout or locomotion run is executed.

Outputs are `sim/scene_barrel_hall.usda`, the updated `sim/drums.json`, generated
textures and `sim/out/hall_barrel_v2/` containing six views, source hashes,
camera poses, configuration checks, the Isaac log and measured GPU runtime.
Native checks verify all 28 placements/IDs, separate rust geometry, both dome
heights, and clean-to-bulged state reset behavior. Opening the USD manually can
use different exposure; run the capture script to reproduce the screenshots.

## Cosmos preview check

After capture, with private `.runtime/cosmos.env` and `.runtime/detector_api.env`:

```sh
python3 tools/review_hall_with_cosmos.py
```

The deployed YOLO model detects the three real RGB close-ups. Cosmos receives
each RGB image, its detector output and a short list of possible follow-ups.
No inventory fault labels, filenames containing expected IDs, temperatures or
gas readings are supplied as observations. `cosmos_review.json` stores the actual
responses and proposed next actions. Responses use a constrained observation/action
schema, and unsupported causal claims are rejected. The first unconstrained review
is retained separately because it included unsupported claims about material state.
No action is executed. This checks the live
model connection without claiming that a complete inspection mission has run.

The existing 1,200-image release, trained weights and detector API are unchanged.
New colour/background combinations still require separate model evaluation;
these preview pictures are not a new accuracy benchmark.
