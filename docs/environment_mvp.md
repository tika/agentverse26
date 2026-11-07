SIMULATION ENVIRONMENT BUILD PROMPT (MVP v1)
Agentverse 2026 hackathon, NVIDIA robotics track

You're helping me build the simulation environment for a hackathon project. I'm new to Isaac Sim, so explain each step in plain language, keep the code simple, and STOP after each step so I can check the result in the viewer before we move on.

======================================================================
0. CONTEXT
======================================================================
- Event: Agentverse 2026 (UCL AI Society), NVIDIA robotics track. The deadline is Sunday 8 Nov, so prefer simple and working over clever.
- Project: an autonomous robot dog inspects a simulated nuclear waste storage hall. It finds corroded and leaking drums with a camera, senses radiation, and decides what to inspect next.
- My role: the Isaac Sim environment. Teammates build (1) a YOLO detector trained on images generated from MY scene, (2) a decision agent, and (3) a live dashboard. They depend on my files, so names, IDs and coordinates must stay EXACTLY as specified below.
- This is a FIRST VERSION (MVP). The goal is a believable, working scene today, not a perfect one.

======================================================================
1. THE REAL-WORLD SITUATION WE ARE SIMULATING
======================================================================
Read this so your visual choices are realistic.

The building is a UK-style interim radioactive waste store: a plain, heavily built reinforced-concrete hall where packaged waste waits, often for decades, until a disposal facility exists. Drums are stored in rows and must be inspected regularly under the site licence. The usual problems after years in storage are:
- humidity and condensation in an unheated building, which corrode painted carbon-steel drums from the bottom rim and under the paint, and
- slow weeping of liquid (water ingress, leachate) that leaves wet patches and dried tide marks on the floor.
Every minute a person spends in the hall adds to their radiation dose, which is why we want a robot to do the inspection.

Waste categories (there is NO high-level waste here; HLW is vitrified and stored differently, never in these drums):
- LLW (low-level waste): 200 L painted carbon-steel drums. Lightly contaminated items such as PPE, tools and rubble. Low dose.
- ILW (intermediate-level waste): 500 L stainless-steel drums, with the waste grouted (set in cement) inside. Higher dose, so these drums are kept in the back zone, away from the entrance.

The hall should look like a real, working, slightly aged industrial nuclear facility: clean and orderly, but clearly used. It should NOT look like a sci-fi set or a pristine CAD render.

======================================================================
2. SETUP AND WORKING RULES
======================================================================
1. Isaac Sim runs on a rented cloud GPU (Ubuntu, RTX-class card). I view it from a Mac with the Isaac Sim WebRTC Streaming Client. You (the coding agent) run ON THE GPU MACHINE.
2. FIRST: find out which Isaac Sim version is installed and how it's launched (app install, or Docker container with headless + livestream). Tell me what you found. After that, use ONLY that version's API. Module names have changed between versions (omni.isaac.* vs isaacsim.*, and the semantics API changed too), so check the installed extensions or this version's docs and never guess. If you aren't sure an API exists, say so and test it with a tiny script first.
3. Run everything as standalone Python scripts (Isaac Sim's python.sh, or inside the container) with livestream enabled so I can watch. Don't rely on pasting code into the Script Editor.
4. Everything is built by re-runnable Python scripts, not by hand. Running the build twice must give the same scene (delete and rebuild /World/Hall, /World/Drums and /World/Defects each time).
5. Units: metres. Z is up. Origin (0, 0, 0) is the hall's front-left floor corner, with x along the length (0 to 20) and y along the width (0 to 12). Yaw is in radians, counter-clockwise from +x.
6. All randomness goes through a single `seed` argument (Python `random.Random(seed)` / `numpy.random.default_rng(seed)`; never global random state), so any layout can be rebuilt exactly.
7. No external asset downloads apart from the built-in robot. All textures are generated procedurally with numpy + PIL and cached in sim/assets/generated/. Textures provided later must be easy to drop in.
8. Materials: use UsdPreviewSurface (diffuse, roughness, metallic, normal and opacity textures) unless it doesn't render correctly in this version, in which case use OmniPBR. Every generated mesh needs UVs (primvars:st).
9. Git: commit after each step that works, and push to the team remote if one is configured. The cloud disk can disappear.

======================================================================
3. TIME LIMITS (IMPORTANT: THIS IS AN MVP)
======================================================================
- Aim for about 30–45 minutes of work per step. If an approach fails 3 times, switch to the simplest fallback, tell me what you dropped, and move on.
- Texture resolution: 1024 px maximum (512 is fine for small decals). Pre-generate a SMALL bank of variants (e.g. 6 rust, 4 stainless-stain, 4 puddle, 1 floor, 1 wall) and reuse them with random rotation, scale and tint. Don't generate a new texture for every defect.
- The full scene build must run in under about 2 minutes.
- Use real-time RTX rendering only. No path tracing, no high sample counts.
- Don't build anything listed in "NOT NOW" at the end.
- Keep each file short and readable. No frameworks, no class hierarchies unless they're really needed.

======================================================================
4. FILE LAYOUT
======================================================================
sim/
  build_hall.py        # builds the hall, drums, labels, writes drums.json; build_scene(seed) callable from other scripts
  textures.py          # procedural texture generation (rust, stains, puddles, floor, wall, label plates)
  drums.py             # drum creation, set_drum_state(), set_drum_category()
  robot.py             # load dog, move_to(x, y), is_moving(), capture_frame()
  events.py            # start_leak(), block_aisle()
  test_render.py       # Step 4 bounding-box proof
  layouts/
    layout_demo.json   # the fixed demo scenario
  drums.json           # written by build_hall.py; the shared "inventory" file
  aisles.json          # aisle centrelines and waypoints for navigation
  assets/              # textures (generated/ + provided later)
  out/                 # test renders and captured frames (git-ignored)
  README.md

======================================================================
5. FIXED HALL LAYOUT (the whole team uses these numbers)
======================================================================
Hall interior: 20 m (x) × 12 m (y) × 6 m tall.

Aisles (walkable, kept clear of drums), numbered 1–3 by increasing y:
- Aisle 1: y = 1.0 to 3.0 (centreline y = 2.0)
- Aisle 2: y = 5.0 to 7.0 (centreline y = 6.0)
- Aisle 3: y = 9.0 to 11.0 (centreline y = 10.0)
Cross-aisles (connect the aisles):
- Front: x = 0 to 2.5 (robot start area)
- Middle: x = 9.0 to 11.0 (also the LLW/ILW zone boundary at x = 10)
- Back: x = 17.5 to 20
Drum bands: y = 3.0–5.0 and y = 7.0–9.0. Each band has 2 rows of drums:
- Row A: y = 3.45 (labels face aisle 1, i.e. −y)
- Row B: y = 4.55 (labels face aisle 2, +y)
- Row C: y = 7.45 (labels face aisle 2, −y)
- Row D: y = 8.55 (labels face aisle 3, +y)
Wall margins (y = 0–1 and 11–12) hold wall-mounted equipment only, with no drums.

LLW zone (x < 10): 16 drums, 4 per row, at x = 3.0, 4.5, 6.0, 7.5.
ILW zone (x ≥ 10): 12 drums, 3 per row, at x = 12.0, 14.0, 16.0.

IDs: D01–D16 are LLW, D17–D28 are ILW. Within each zone, number by row (A, B, C, D), then by increasing x. Example: D01 = (3.0, 3.45), D04 = (7.5, 3.45), D05 = (3.0, 4.55), D17 = (12.0, 3.45), D28 = (16.0, 8.55).
Positions are exact (no positional jitter). Each drum body gets a random yaw (seeded) so they don't all look identical, but the label plate always faces its aisle.

Robot start: (1.0, 6.0), facing +x (looking down aisle 2).

Write aisles.json with the aisle and cross-aisle rectangles plus a simple waypoint graph: the intersections of the aisle centrelines (y = 2, 6, 10) with the cross-aisle centrelines (x = 1.25, 10.0, 18.75), plus points every 1.5 m along each aisle centreline.

======================================================================
6. BUILD STEPS (stop and show me after each one)
======================================================================

----------------------------------------------------------------------
STEP 0: Version check
----------------------------------------------------------------------
Report the Isaac Sim version, the launch method, the exact launch command with livestream, and the correct module names for: stage/prim utilities, semantics labelling, Replicator writers/annotators, cameras, and the quadruped/policy examples. Write a 10-line hello-world script that opens a stage with a cube and livestreams it. Then stop.
✅ Check: I can see the cube in the WebRTC client.

----------------------------------------------------------------------
STEP 1: The hall
----------------------------------------------------------------------
Build with simple primitives (cubes, cylinders) plus procedural textures:

Floor
- Concrete slab with a light-grey epoxy coating (sealed so it can be decontaminated): slightly glossy (roughness about 0.4–0.55), subtle mottling, faint trowel marks, scuffs, a few old dried stains and wheel marks.
- Painted markings: yellow aisle edge lines (100 mm wide), a yellow/black hatched band across the floor at x = 10 marking the LLW/ILW boundary, and stencilled zone text "LLW STORE – ZONE A" and "ILW STORE – ZONE B" on the floor near each zone's front edge (PIL text texture on a thin quad).
- Paint the markings and old stains into the floor texture or onto unlabelled quads. They are deliberate realistic distractors and get NO semantic class.

Walls (4 walls, 6 m high, 0.5 m thick, outside the 20 × 12 interior)
- Bare cast concrete with visible formwork panel joints and a regular grid of small dark form-tie holes. Light staining, and darker water streaks below a few tie holes.
- The bottom 1.5 m is painted with a decontaminable coating (pale grey or green) and has a clear top edge line.
- Front wall (x = 0): a closed roller-shutter door (3 m wide, centred at y = 6) and a personnel door at about y = 2.5, with a yellow trefoil sign "CAUTION – RADIATION CONTROLLED AREA" beside it.

Overhead (simple boxes and cylinders, unlabelled)
- Ceiling slab at z = 6.
- Overhead travelling crane: two runway rails along the long walls at z = 5.2, and one crane bridge beam parked across the hall at x ≈ 18.5, painted crane-yellow.
- One rectangular ventilation duct along the ceiling centreline and cable trays on the side walls at z = 3.

Wall-mounted equipment (low-poly boxes, unlabelled)
- 4 area gamma monitors (small grey boxes with an amber beacon) at about 2 m height, 2 per long wall.
- CCTV cameras in 2 corners.
- Zone signs at each zone ("LLW", "ILW" with trefoil). A fire point near the door.
Keep the total to about 30 extra prims. These details make it read as a real facility, so don't over-model them.

Lighting
- 2 rows of 4 high-bay LED fixtures (rectangle lights) at z ≈ 5.5, above aisles 1–2 and 2–3, colour about 5000 K (cool white).
- A dim dome/ambient light so shadowed areas aren't pure black.
- Target: aisles bright enough for a camera, soft shadows under and between drums, corners noticeably darker. One fixture in the ILW zone runs at about 40% (a realistic failing light, which also adds lighting variation).
- All lights live under /World/Hall/Lights with stable names so they can be randomised later.

✅ Check: an empty, lit hall in the viewer that looks like a real nuclear store, not a grey box.

----------------------------------------------------------------------
STEP 2: Drums and waste categories
----------------------------------------------------------------------
| Category | Size | Look | Zone | Count |
|---|---|---|---|---|
| LLW | 200 L: 0.58 m diameter × 0.88 m tall | painted carbon steel | x < 10 | 16 (D01–D16) |
| ILW | 500 L: 0.80 m diameter × 1.20 m tall | bare stainless steel | x ≥ 10 | 12 (D17–D28) |

LLW drum geometry (simple, but recognisable as a real 200 L drum):
- Cylinder body, plus 2 rolling hoops (thin rings slightly proud of the body at 1/3 and 2/3 height), plus top and bottom chimes (rims), plus a flat lid with 2 small bungs.
- Paint: industrial semi-gloss in a muted colour (e.g. faded yellow, mid-grey or blue, picked per drum by seed). Add slight fading, edge wear on the chimes where bare steel shows, light dust on the lid, and scuffs. CLEAN drums must still look used: grime and scuffs, but NO rust.

ILW drum geometry (500 L stainless):
- Cylinder body, a visible circumferential lid weld/seam line just below the top, a lid with a raised lifting flange/grab ring, and a small vent filter housing on the lid.
- Material: brushed stainless (metallic 1.0, roughness about 0.3–0.4, faint vertical brushing in the roughness map), slightly dulled with light dust. It should look clearly different from the LLW drums at a glance.

Label plates (unlabelled, no semantic class):
- A thin plate (about 0.20 × 0.14 m) on the drum side at about 60% height, facing the drum's aisle, 2 mm off the surface.
- PIL-generated texture: a yellow background with a black trefoil (drawn with shapes; no font or asset needed), the category in large text ("LLW"/"ILW"), the ID ("D07"), and a fake barcode strip. One PNG per drum.

Prim paths:
- Drum root: /World/Drums/D01 (an Xform). Children: Body (the main cylinder that gets the "drum" class), Hoops, Lid, Plate, etc.
- Defects go under /World/Defects/D01/... (see Step 3).

drums.json, one entry per drum (keep these keys; teammates rely on them):
{"id": "D07", "category": "LLW", "zone": "A", "row": "B",
 "x": 6.0, "y": 4.55, "yaw": 1.23, "radius": 0.29, "height": 0.88,
 "facing_aisle": 2, "state": "clean", "defects": [],
 "source_strength": 1, "prim_path": "/World/Drums/D07"}
- x and y are the drum centre on the floor. source_strength: LLW = 1, ILW = 20 (simulation units, for the radiation model later).
- "state" is "clean", "corroded", "leaking" or "corroded+leaking".
- "defects" is a list like {"type": "corrosion", "prim_path": "...", "z": 0.12, "angle": 2.1, "size": 0.15}.

Also write set_drum_category(drum_id, category), which swaps the size, material, plate and source_strength, and updates drums.json.

✅ Check: two clearly different drum types in two zones, readable labels when I zoom in, and drums.json matches the scene (print a table).

----------------------------------------------------------------------
STEP 3: Drum condition states (AUTHENTICITY MATTERS MOST HERE)
----------------------------------------------------------------------
Write set_drum_state(drum_id, state, seed). State is "clean", "corroded", "leaking" or "corroded+leaking". Calling it again replaces that drum's old defects (re-runnable).

The defects must look like real degradation in a waste store, not a flat brown blob. The detector is trained on these images, so realism here directly affects the project.

GEOMETRY RULE (important for correct bounding boxes): Replicator's boxes come from the mesh, not the texture's transparency. So each defect's mesh OUTLINE must follow the defect's visible shape:
- Generate an irregular outline (a noisy, lobed polygon: radial noise with 3–4 octaves, about 48–64 vertices).
- Build the mesh from that outline. Use transparency only for a soft ragged fringe in the outer ~10%, so the box stays tight.
- Each rust patch is its own mesh, CURVED to sit on the drum's cylinder at radius + 3 mm (map the outline in angle/height space onto the cylinder). It is never baked into the drum texture.
- Each puddle is its own flat mesh 2 mm above the floor.

3a. Corrosion on LLW drums (painted carbon steel). 1–3 patches per corroded drum. Pick from these real patterns, weighted:
- 50%: base/bottom-chime corrosion. Rust along the bottom 0–25% of the drum where condensation collects. A wide, low patch hugging the bottom rim, the most common real failure.
- 25%: lid/top-chime corrosion. Water pools on the lid, so rust forms around the top rim with RUN-OFF STREAKS: narrow orange-brown streaks 10–40 cm long running down the side, fading as they go. A streak is part of the same corrosion patch (or its own "corrosion" mesh).
- 25%: under-film corrosion at a rolling hoop or a scuff. Paint BLISTERING (raised bubbles, slightly lighter edge ring) with rust breaking through, and flaking paint chips at the boundary showing bare metal.
Texture recipe (procedural, numpy + PIL):
- Colour ramp following real iron oxides: dark umber/black-brown core (about #2E1A10 to #4A2614), reddish-brown body (#6B3419 to #8A4320), bright orange active rust (#B5591F), and yellow-ochre bloom at the edges (#C99045). Not uniform: mottled with fractal noise and domain warping.
- Pitting: small dark pits clustered in the core.
- Edges: a ring where the paint lifts and flakes (lighter, a few cm wide), then the surrounding paint.
- Roughness 0.85–1.0 in the rust, matte compared with the semi-gloss paint. A normal/bump map from the same height noise, so the rust looks crusty and raised and the blisters look raised.
- Size: 8–35 cm across (an outline at least 8 cm wide so it is detectable).

3b. Corrosion on ILW drums (stainless steel). Stainless doesn't rust like carbon steel. Use what really happens to stainless in stores:
- Tea staining: a patchy, low-contrast light-to-mid brown discolouration (#A0794A to #7A5530 at partial strength) over an area of 15–40 cm, often on the upper half.
- Pitting with weeping: a cluster of tiny dark-brown pits, each with a thin orange-brown streak running downward, typically near the lid weld seam or the base.
1–2 patches per corroded ILW drum. Keep the metal's shine around them; the stain itself is slightly duller. These are subtler than LLW rust. That is realistic and intentional, but keep them visible from 1–3 m.

3c. Leaks ("leaking" state). One puddle per leaking drum:
- Shape: an irregular lobed outline (not a circle) that touches the drum base, elongated 1.5–2.5× in a seeded direction (the floor's slight fall), 0.3–1.0 m long. Placed on the aisle-facing side where possible, so it can spread a little into the aisle (a real trip and contamination hazard).
- Look: like WET floor, not paint.
  - The centre is a darkened, slightly tinted version of the floor colour with very low roughness (0.02–0.08), so it shows the overhead lights as reflections. This is the key realism cue.
  - The edges get rougher and lighter as the film thins.
  - 1–2 faint concentric tide-mark rings just outside the wet edge (dried residue from earlier evaporation), part of the same puddle mesh/texture.
- Tint by category:
  - LLW: rust-tinged amber-brown leachate (the liquid picks up iron oxide from the corroding drum).
  - ILW: nearly clear, slightly milky grey leachate from the grout, with a thin WHITE crystalline crust (efflorescence) at the tide marks and at the drum base seam.
- Drum base staining: a dark wet band on the bottom 2–5 cm of the drum on the leak side, and on LLW a thin weep trail from the bottom chime down to the puddle. This band is part of the puddle mesh or its own "spill" mesh. It is never baked into the drum.

A drum can be both corroded and leaking. Update "state" and "defects" in drums.json every time.
Prim paths: /World/Defects/D07/Corrosion_0, Corrosion_1, ..., /World/Defects/D07/Spill_0.

✅ Check: I can switch any drum between states. From 1–3 m, rust looks crusty and layered (not a flat sticker), stainless staining looks like stainless staining, and puddles look wet and reflective. Show me close-ups of one LLW corroded drum, one ILW corroded drum, one LLW leak and one ILW leak.

----------------------------------------------------------------------
STEP 4: Semantic labels (CRITICAL: the training data depends on this)
----------------------------------------------------------------------
Use this version's semantics labelling API (check its name; it changed between versions). Each labelled prim gets TWO semantic types:
- type "class": the drum Body gets "drum", each corrosion mesh gets "corrosion", each spill mesh gets "spill"
- type "drum_id": the ID of the drum it belongs to, e.g. "D07" (on the body AND on its defects)
Label plates, hoops, lids, walls, floor, signs and equipment get NO class. Only the Body cylinder gets "drum", unless the hoops/lid can share the label easily. If they can, label the whole drum Xform "drum" so the box covers the full drum. Tell me which you chose.

Then prove it with test_render.py:
- Set one LLW drum to "corroded+leaking" (fixed seed).
- Place a camera 2 m in front of it at 0.6 m height, tilted 10° down, at 640×640.
- Use Replicator to render ONE frame and save the RGB image plus 2D tight bounding boxes (semantic type "class"), including the drum_id for each box.
- Draw the boxes on the image with class + drum_id text and save it as sim/out/test_render/boxes.png.
- Print the box list.
- Do the same for one ILW drum.

✅ Check: the saved images show correct, tight boxes around the drum, each rust patch and the puddle, and nothing around the plates, floor markings or old floor stains.

----------------------------------------------------------------------
STEP 5: Robot dog and move_to
----------------------------------------------------------------------
- Load one of this version's built-in quadrupeds (Spot, ANYmal or a Unitree model). Spawn it at (1.0, 6.0) facing +x.
- move_to(x, y) must be NON-BLOCKING. It sets a goal and returns immediately. A physics/update callback moves the robot each tick. is_moving() and get_pose() -> (x, y, yaw) report status. A blocking loop would freeze the viewer and the sim, so don't use one.
- Navigation: plan a path over the aisles.json waypoint graph (a simple shortest path is fine), so the robot only travels along aisles and never passes through drums. If the target point isn't on the graph, go to the nearest waypoint, then straight to the target if that's inside an aisle.
- MODE = "slide" is the DEFAULT for the MVP: move the robot's root smoothly along the path (about 0.5 m/s, turning toward the direction of travel, legs in a standing pose, no physics on the legs). The whole team depends on move_to working, so make this one solid first.
- MODE = "walk" (optional, time-box 45 min): use the built-in walking policy, driven by velocity commands toward the next waypoint. If it's unreliable, say so, leave it switched off behind the flag, and move on.

✅ Check: the dog moves to 3 different points (e.g. (6.0, 2.0), (14.0, 6.0), (18.75, 10.0)) without going through drums, and is_moving() turns false when it arrives.

----------------------------------------------------------------------
STEP 6: Cameras on the dog
----------------------------------------------------------------------
Attach to the dog's body (as child prims, so they move with it):
- an RGB camera and a depth camera at the same pose: 0.6 m above the floor, facing forward, tilted 10° down, 640×640, a realistic wide-ish lens (about 70–90° horizontal field of view).
capture_frame(out_dir) saves:
- rgb_XXXX.png
- depth_XXXX.npy (float32, metres)
- meta_XXXX.json: robot pose (x, y, yaw), camera world position and rotation, camera intrinsics (fx, fy, cx, cy, width, height), sim time.

✅ Check: a saved frame shows the drums from the dog's point of view, and the depth values look sensible (about 1–5 m to nearby drums).

----------------------------------------------------------------------
STEP 7: Demo layout and events
----------------------------------------------------------------------
layouts/layout_demo.json, a fixed scenario:
{"seed": 42,
 "states": {"D03": "corroded", "D10": "corroded+leaking", "D20": "corroded",
            "D25": "corroded", "D27": "leaking"},
 "robot_start": [1.0, 6.0, 0.0]}
(This is 4 corroded and 2 leaking, with defects in both zones and on aisle-facing sides. All other drums are clean.)
load_layout(path) rebuilds the scene exactly: same defects, same shapes, same textures.

Prepare (but don't trigger) two mid-run events in events.py, each a function that works WHILE the sim is running:
- start_leak(drum_id, seed=0): adds a spill to that drum. Grow it from 20% to 100% scale over about 5 s (simple and convincing). Labels it "spill" + drum_id and updates drums.json.
- block_aisle(aisle_number, x=None): places a realistic obstruction (a yellow steel pallet stillage or a stack of 2 crates with hazard tape) across the aisle at x (default: the aisle's middle in the LLW zone). No semantic class. Marks the blocked waypoints in aisles.json (or in memory, exposed through get_blocked()) so move_to re-routes around it.

✅ Check: load_layout gives the same scene every time (render the same frame twice and compare the images), and both events work while the sim is running.

----------------------------------------------------------------------
STEP 8: Save and document
----------------------------------------------------------------------
- Save the demo scene as sim/scene_demo.usd (textures referenced by relative path).
- README.md with EXACT commands to:
  - launch Isaac Sim with livestream
  - build the hall
  - load the demo layout
  - move the dog
  - save a camera frame
  - trigger both events
  - change a drum's state
- List known limitations and anything you dropped because of the time limits.

======================================================================
7. DELIVERABLES
======================================================================
- The scripts above
- drums.json, aisles.json, layouts/layout_demo.json
- sim/scene_demo.usd
- sim/out/test_render/ (the Step 4 proof images)
- README.md