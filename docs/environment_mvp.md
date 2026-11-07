SIMULATION ENVIRONMENT BUILD PROMPT (MVP v2)
Agentverse 2026 hackathon, NVIDIA robotics track

You're helping me build the simulation environment for a hackathon project. I'm new to Isaac Sim, so explain each step in plain language, keep the code simple, and STOP after each step so I can check the result in the viewer before we move on.

======================================================================
0. CONTEXT
======================================================================
- Event: Agentverse 2026 (UCL AI Society), NVIDIA robotics track. The deadline is Sunday 8 Nov, so prefer simple and working over clever.
- Project: an autonomous robot dog inspects a simulated nuclear waste storage hall. It finds faulty drums with a camera and depth sensor, senses radiation, and decides what to inspect next.
- My role: the Isaac Sim environment. Teammates build (1) a YOLO detector trained on images generated from MY scene, (2) a decision agent, and (3) a live dashboard. They depend on my files, so names, IDs and coordinates must stay EXACTLY as specified below.
- This is a FIRST VERSION (MVP). The goal is a believable, working scene today, not a perfect one.

======================================================================
1. THE REAL-WORLD SITUATION WE ARE SIMULATING
======================================================================
Read this so your visual choices are realistic.

The building is a UK-style interim radioactive waste store: a plain, heavily built reinforced-concrete hall where packaged waste waits, often for decades, until a disposal facility exists. Drums are stored in rows and must be inspected regularly under the site licence. Every minute a person spends in the hall adds to their radiation dose, which is why we want a robot to do the inspection.

Waste categories (there is NO high-level waste here; HLW is vitrified and stored differently, never in these drums):
- LLW (low-level waste): 200 L painted carbon-steel drums. Lightly contaminated items such as PPE, tools and rubble. Low dose.
- ILW (intermediate-level waste): 500 L stainless-steel drums, with the waste grouted (set in cement) inside. Higher dose, so these drums are kept in the back zone, away from the entrance.

Why drums degrade in a store like this:
- The building is unheated, so humidity rises and falls with the weather. Condensation forms on cold metal, runs down, and collects at the bottom rim, on top of rolling hoops and inside the lid rim.
- Airborne dust and chlorides settle on upper surfaces and attack even stainless steel over time.
- Handling (forklifts, drum grabs, clamps) scrapes paint off and leaves bare steel that then rusts.
- Inside the drums, some waste corrodes or reacts and generates gas or expanding products. This can make a drum bulge, and liquid can slowly weep out through seals, bungs or corroded spots.

The hall should look like a real, working, slightly aged industrial nuclear facility: clean and orderly, but clearly used. It should NOT look like a sci-fi set or a pristine CAD render.

======================================================================
2. FAULT TAXONOMY (what we simulate, how it's labelled, what the robot can know)
======================================================================
These are the real problems an inspection looks for. Build the scene so each one is represented honestly. The robot should only be able to "see" what a real camera and depth sensor could see.

| Fault | Why it matters | What the robot can observe | How we simulate it | YOLO class |
|---|---|---|---|---|
| External corrosion | Can weaken the container over time | Rust patches, damaged or blistered coating, pitting, run-off streaks, discolouration | Separate conforming meshes on the drum surface (Step 3) | "corrosion" |
| Suspected release | Material may have escaped containment | Wet liquid, dried stains, crystalline deposits, weep trails | Separate meshes on the floor and drum (Step 4) | "spill" |
| Bulging / distortion | Can indicate internal gas or expansion, or other deterioration | Shape differs from the nominal drum: domed lid, barrel-shaped sides, dents | Deformed drum mesh (Step 5). Visible in depth and silhouette | none (detected by comparing shape with drums.json nominal size) |
| Obstructed inspection access | Prevents adequate inspection of an area | Blocked aisle, drum face hidden behind an object | Obstruction objects (Steps 5 and 9) | none |
| Internal corrosion | Damages a package without initially being visible outside | Nothing reliable from a camera | A hidden ground-truth flag ONLY. No visual. Optionally combined with a slight bulge | none |

Rules that follow from this table:
- The YOLO classes stay exactly "drum", "corrosion" and "spill". Bulging and obstruction are handled by geometry and logic, not by YOLO.
- Everything is written as ground truth into drums.json, so teammates can score the robot's findings. The agent maps findings to the statuses OK / Suspect / Confirmed defect / Couldn't inspect. That logic is not your job, but your ground truth must make it possible.
- Hard negatives (things that must NOT be labelled, so the detector learns the difference):
  - cosmetic scuffs and polish marks on paint (no bare steel bigger than a few mm, no orange)
  - dust and grime
  - weld heat tint on stainless
  - floor scuffs, wheel marks and worn floor paint
  - wall water streaks
  - label plates and signs
  Do NOT put liquid-like or tide-mark stains on the floor as decoration. Floor stains near drums are reserved for the "spill" class.

======================================================================
3. SETUP AND WORKING RULES
======================================================================
1. Isaac Sim runs on a rented cloud GPU (Ubuntu, RTX-class card). I view it from a Mac with the Isaac Sim WebRTC Streaming Client. You (the coding agent) run ON THE GPU MACHINE.
2. FIRST: find out which Isaac Sim version is installed and how it's launched (app install, or Docker container with headless + livestream). Tell me what you found. After that, use ONLY that version's API. Module names have changed between versions (omni.isaac.* vs isaacsim.*, and the semantics API changed too), so check the installed extensions or this version's docs and never guess. If you aren't sure an API exists, say so and test it with a tiny script first.
3. Run everything as standalone Python scripts (Isaac Sim's python.sh, or inside the container) with livestream enabled so I can watch. Don't rely on pasting code into the Script Editor.
4. Everything is built by re-runnable Python scripts, not by hand. Running the build twice must give the same scene (delete and rebuild /World/Hall, /World/Drums, /World/Defects and /World/Obstructions each time).
5. Units: metres. Z is up. Origin (0, 0, 0) is the hall's front-left floor corner, with x along the length (0 to 20) and y along the width (0 to 12). Yaw is in radians, counter-clockwise from +x.
6. All randomness goes through a single `seed` argument (Python `random.Random(seed)` / `numpy.random.default_rng(seed)`; never global random state), so any layout can be rebuilt exactly.
7. No external asset downloads apart from the built-in robot. All textures are generated procedurally with numpy + PIL and cached in sim/assets/generated/. Textures provided later must be easy to drop in.
8. Materials: use UsdPreviewSurface (diffuse, roughness, metallic, normal and opacity textures) unless it doesn't render correctly in this version, in which case use OmniPBR. Every generated mesh needs UVs (primvars:st).
9. Git: commit after each step that works, and push to the team remote if one is configured. The cloud disk can disappear.

======================================================================
4. TIME LIMITS (IMPORTANT: THIS IS AN MVP)
======================================================================
- Aim for about 30–45 minutes of work per step. If an approach fails 3 times, switch to the simplest fallback, tell me what you dropped, and move on.
- Texture resolution: 1024 px maximum (512 is fine for small decals). Pre-generate a SMALL bank of variants and reuse them with random rotation, scale, crop and tint. Don't generate a new texture for every defect. Suggested bank:
  - LLW rust: 2 variants per stage × 4 stages = 8
  - ILW stainless: 2 tea-stain + 2 pitting = 4
  - Wet spill: 3. Dried residue: 3. Deposit crust: 2
  - Floor: 1. Wall: 1. Paint: 1 per colour. Brushed stainless: 1
  The bank must generate in under about 1 minute and is cached after the first run.
- The full scene build must run in under about 2 minutes.
- Use real-time RTX rendering only. No path tracing, no high sample counts.
- Don't build anything listed in "NOT NOW" at the end.
- Keep each file short and readable. No frameworks, no class hierarchies unless they're really needed.

======================================================================
5. FILE LAYOUT
======================================================================
sim/
  build_hall.py        # builds the hall, drums, labels, writes drums.json; build_scene(seed) callable from other scripts
  textures.py          # procedural texture bank (rust stages, stainless, spills, residue, deposits, floor, wall, plates)
  drums.py             # revolved drum meshes, set_drum_faults(), set_drum_category()
  defects.py           # corrosion, release, bulge/dent builders
  robot.py             # load dog, move_to(x, y), is_moving(), capture_frame()
  events.py            # start_leak(), block_aisle(), obstruct_drum()
  test_render.py       # bounding-box proof
  layouts/
    layout_demo.json   # the fixed demo scenario
  drums.json           # written by the build; the shared "inventory" + ground-truth file
  aisles.json          # aisle rectangles and waypoints for navigation
  assets/              # textures (generated/ + provided later)
  out/                 # test renders and captured frames (git-ignored)
  README.md

======================================================================
6. FIXED HALL LAYOUT (the whole team uses these numbers)
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

IDs: D01–D16 are LLW, D17–D28 are ILW. Within each zone, number by row (A, B, C, D), then by increasing x.
- LLW: row A = D01–D04, row B = D05–D08, row C = D09–D12, row D = D13–D16.
- ILW: row A = D17–D19, row B = D20–D22, row C = D23–D25, row D = D26–D28.
Example: D01 = (3.0, 3.45), D06 = (4.5, 4.55), D22 = (16.0, 4.55), D28 = (16.0, 8.55).
Positions are exact (no positional jitter). Each drum body gets a random yaw (seeded) so they don't all look identical, but the label plate always faces its aisle.

Robot start: (1.0, 6.0), facing +x (looking down aisle 2).

Write aisles.json with the aisle and cross-aisle rectangles plus a simple waypoint graph: the intersections of the aisle centrelines (y = 2, 6, 10) with the cross-aisle centrelines (x = 1.25, 10.0, 18.75), plus points every 1.5 m along each aisle centreline.

======================================================================
7. BUILD STEPS (stop and show me after each one)
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
- Concrete slab with a light-grey epoxy coating (sealed so it can be decontaminated): slightly glossy (roughness about 0.4–0.55), subtle mottling, faint trowel marks, a few patched concrete repairs (slightly different grey, rectangular), scuffs and black rubber wheel marks along the aisles.
- One floor drain grate per long wall margin (a dark grid square).
- Painted markings: yellow aisle edge lines (100 mm wide, worn thin where traffic crosses), a yellow/black hatched band across the floor at x = 10 marking the LLW/ILW boundary, and stencilled zone text "LLW STORE – ZONE A" and "ILW STORE – ZONE B" on the floor near each zone's front edge (PIL text texture on a thin quad).
- NO liquid-looking stains or tide marks in the floor texture (see the hard-negative rules in section 2).

Walls (4 walls, 6 m high, 0.5 m thick, outside the 20 × 12 interior)
- Bare cast concrete with visible formwork panel joints (about 2.4 × 1.2 m grid) and a regular grid of small dark form-tie holes. Light grey staining, and darker grey (NOT orange) water streaks below a few tie holes.
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

Build each drum body as a REVOLVED-PROFILE MESH:
- Write a list of (radius, height) points, then spin it around Z in 64 segments.
- UVs: u = angle / 2π, v = height / drum height.
- One function, make_drum_mesh(profile, bulge=None, dents=None), so bulging and dents (Step 5) are just profile or vertex changes, and the hoops and chimes come for free from the profile.
- Fallback: if this fights you for more than 30 minutes, use a cylinder plus thin ring cylinders. Then bulging falls back to non-uniform scaling of the body plus a raised lid.

LLW drum (200 L, painted carbon steel). The profile includes:
- a bottom chime: a rolled rim, 10–15 mm proud, at the base
- 2 rolling hoops: rounded ridges about 10 mm proud, at 1/3 and 2/3 height
- a top chime rim with a recessed lid inside it (about 15 mm down)
Also:
- 2 small bungs on the lid (a 2" one and a 3/4" one).
- A faint vertical side-seam weld line (in the texture/normal map) at a seeded angle.
- Paint: industrial semi-gloss (roughness about 0.35) in a muted colour picked per drum by seed (faded safety yellow, mid-grey, or dark blue), slightly faded and uneven.
- Clean drums must still look used: dust on the lid, grime darkening near the base, small cosmetic scuffs. No bare steel bigger than a few mm and NO orange anywhere.

ILW drum (500 L, stainless steel, grouted waste). The profile includes:
- a plain straight body
- a raised lid flange/grab ring at the top
- a lid seam with a circumferential weld bead about 30 mm below the top
Also:
- A small cylindrical vent filter housing on the lid.
- Material: brushed stainless (metallic 1.0, roughness about 0.3–0.4, with fine vertical brushing in the roughness map), slightly dulled with dust on the upper surfaces.
- Weld heat tint: a faint straw/bronze band 1–2 cm wide along the weld bead on ALL ILW drums. It's realistic, and it's a hard negative (no class).
- It should look clearly different from the LLW drums at a glance.

Label plates (unlabelled, no semantic class):
- A thin plate (about 0.20 × 0.14 m) on the drum side at about 60% height, facing the drum's aisle, 2 mm off the surface.
- PIL-generated texture: a yellow background with a black trefoil (drawn with shapes; no font or asset needed), the category in large text ("LLW"/"ILW"), the ID ("D07"), and a fake barcode strip. One PNG per drum.

Prim paths:
- Drum root: /World/Drums/D01 (an Xform). Children: Body (the revolved mesh that gets the "drum" class), Lid parts, Plate.
- Defects go under /World/Defects/D01/...
- Obstructions go under /World/Obstructions/...

drums.json, one entry per drum (keep these keys; teammates rely on them):
{"id": "D07", "category": "LLW", "zone": "A", "row": "B",
 "x": 6.0, "y": 4.55, "yaw": 1.23, "radius": 0.29, "height": 0.88,
 "facing_aisle": 2, "source_strength": 1, "prim_path": "/World/Drums/D07",
 "state": "clean",
 "faults": [],
 "corrosion_severity": 0,
 "defects": [],
 "shape": {"max_radius": 0.29, "lid_rise": 0.0, "dents": []},
 "obstructed": false,
 "internal_corrosion": false}
- x and y are the drum centre on the floor.
- radius and height are always the NOMINAL values. The real shape is in "shape".
- source_strength: LLW = 1, ILW = 20 (simulation units, for the radiation model later).
- "state" is "clean", or the sorted fault names joined with "+" (e.g. "corrosion+leak").

Also write set_drum_category(drum_id, category), which swaps the size, material, plate and source_strength, and updates drums.json.

✅ Check: two clearly different drum types in two zones, real-looking drum details (hoops, chimes, lid), readable labels when I zoom in, and drums.json matches the scene (print a table).

----------------------------------------------------------------------
STEP 3: External corrosion (AUTHENTICITY MATTERS MOST HERE)
----------------------------------------------------------------------
Write set_drum_faults(drum_id, faults, seed, severity=2), where faults is a list drawn from:
"corrosion", "leak", "residue", "bulge", "dent", "obstructed", "internal_corrosion" (an empty list means clean). Calling it again REPLACES that drum's old defects (re-runnable). This step implements "corrosion". Steps 4 and 5 add the rest.

The detector is trained on these images, so realism here directly affects the project. Real rust is NOT a flat brown blob. It is layered, it follows where water sits, it changes the paint around it, and gravity pulls stains downward.

GEOMETRY RULE (important for correct bounding boxes): Replicator's boxes come from the mesh, not the texture's transparency. So each defect's mesh OUTLINE must follow the defect's visible shape:
- Generate an irregular outline (a noisy, lobed polygon: radial noise with 3–4 octaves, about 48–64 vertices). Streaks are elongated outlines.
- Build the mesh from that outline. Use transparency only for a soft ragged fringe in the outer ~10%, so the box stays tight.
- Each corrosion feature is its own mesh, CURVED to sit on the drum surface 3 mm outside the local profile radius (map the outline in angle/height space onto the revolved profile, so it also hugs hoops, chimes and bulges).
- Never bake corrosion into the drum texture.
- Each corrosion mesh: at least 6 cm in its smallest dimension, so it is detectable.

3a. LLW corrosion (painted carbon steel)
Severity 1–3 controls the mix of stages: 1 = mostly stage 1–2, 2 = stage 2–3, 3 = stage 3–4.
Each corroded drum gets 1–3 patches. Location (weighted by where water and handling damage really occur):
- 45%: bottom chime band (0–20% height), the most common real failure because condensation runs down and sits where the drum meets the floor. Wide, low patches (20–50 cm long around the circumference, 6–15 cm tall) hugging and wrapping over the rim. The rim edge itself is the most corroded, and the rust fades upward.
- 20%: top chime / lid rim. Water pools in the recessed lid, so a rust ring forms around the inside and over the top edge of the chime, with RUN-OFF STREAKS running down the side (see below).
- 20%: along the TOP edge of a rolling hoop, where water sits on the ridge. A thin rust line along the hoop, 10–30 cm long, with short streaks dripping below it.
- 15%: handling damage at 40–70% height. Horizontal scrape marks (forklift/drum-grab) where paint is gouged off, with orange rust in the gouges.
Optional: one patch follows the vertical side-seam weld.

Stages (each patch picks one stage; the texture bank has 2 variants per stage):
- Stage 1, coating damage / early rust: scratches and chips through the paint showing bare grey steel, with a fine orange FLASH RUST bloom along the scratch lines and a thin orange-brown halo staining into the surrounding paint. Mostly paint colour, with thin rust lines. Slightly matte.
- Stage 2, under-film corrosion / blistering: clusters of round paint blisters (3–15 mm, raised in the normal map, slightly lighter edge where the paint stretches). Some blisters are burst, with orange-brown centres. Rust "creeps" under the paint: an irregular lifted-paint boundary with brown staining bleeding into the paint 1–3 cm beyond it. Some flaking paint chips curl at the edge.
- Stage 3, established rust: paint gone over the patch. LAYERED colour following real iron oxides:
  - near-black/dark brown base (magnetite, #2B1A12 to #3D2416) in the deepest parts and pits
  - red-brown body (hematite, #6B3419 to #8A4320)
  - bright orange active rust (lepidocrocite, #B5591F to #C46A2B) in a patchy, mottled pattern
  - yellow-ochre bloom (goethite, #C99045 to #D4A55A) as a powdery haze at the edges and on the upper side
  Texture: rough, crusty and granular (roughness 0.9–1.0), with a strong normal/bump map. Scale lifts in thin layers (laminar flaking), with hard-edged flakes slightly raised. Pitting craters 1–5 mm, darker inside. A ring of blistered paint around the whole patch (stage-2 border).
- Stage 4, severe (bottom chime only, about 10% of patches at severity 3): the chime rim looks eaten, with an irregular, ragged lower edge (cut into the outline), heavy dark scale, and 1–3 small dark perforation spots. A small fan of orange-brown rust flakes and powder on the floor within 10 cm of the base (its own small mesh, also class "corrosion", same drum_id).

Run-off streaks (used with top-chime and hoop patches; class "corrosion"):
- Start at the source, 1–4 cm wide, running straight DOWN under gravity with a slight waver. Sometimes 2–3 branches.
- Darkest and most orange at the source, fading to a thin translucent brown tint over 10–40 cm.
- They pause and widen slightly where they meet a hoop, then continue below it.
- Each streak is its own elongated mesh or part of the source patch's mesh. Keep them thin, so the box stays honest.

Paint interaction: the paint around every patch is discoloured (orange-brown tint in a 1–3 cm halo) and slightly lifted. Rust should look like it is coming FROM the drum, not stuck on top.
Colour interaction: rust reads as strong orange on blue/grey paint and as brown-orange on yellow paint. Tune the halo so it is visible on all 3 paint colours.

3b. ILW corrosion (stainless steel)
Stainless doesn't rust like carbon steel. It shows subtler, specific damage. Severity 1–3 controls how many features there are and their size and contrast. Each corroded drum gets 1–3 features:
- Tea staining (40%): patchy, cloudy light-to-mid brown discolouration (#A0794A to #6E4B2A at 30–70% strength, so the metal shows through), 15–40 cm across. Mostly on the UPPER half and on the lid flange, where dust and chlorides settle. Diffuse, irregular, slightly blotchy edges. The metal stays shiny around it, and the stained area is a bit duller (roughness +0.15).
- Pitting with weeping (35%): a cluster of 5–30 tiny pits (1–3 mm dark-brown/black dots, slightly recessed in the normal map) within a 5–15 cm area, usually near the lid weld seam or the lower 20% of the body. Each pit has a thin orange-red weep streak (2–6 mm wide, 3–15 cm long) running straight down. The cluster plus its streaks is one corrosion mesh.
- Crevice corrosion (25%): a thin brown-black line with brown staining spreading 1–3 cm from it, in a crevice: just under the lid flange, along the lid seam, or along the bottom edge where the drum meets the floor. The mesh is a thin curved band 10–40 cm long.
- Severity 3 only: fine dark branching hairline cracks (stress corrosion cracking) about 5–10 cm long next to the weld, with brown staining along them. They're part of the crevice or pitting mesh.
These are subtler than LLW rust. That is realistic and intentional, but every feature must still be visible from 1–3 m in normal hall lighting.

Write all of it into drums.json ("faults", "corrosion_severity", "defects" with {"type": "corrosion", "subtype": "stage3" / "tea_stain" / "pitting" / ..., "prim_path", "z", "angle", "size"}).
Prim paths: /World/Defects/D07/Corrosion_0, Corrosion_1, ...

✅ Check: show me close-ups from about 1.5 m of LLW corrosion at severities 1, 2 and 3 (on different paint colours), and of ILW corrosion at severities 1 and 3. Rust should look crusty, layered and gravity-driven, not like a sticker. Stainless damage should look like stainless damage.

----------------------------------------------------------------------
STEP 4: Suspected release ("leak" and "residue")
----------------------------------------------------------------------
Release evidence = material may have escaped. It is all class "spill". There are two faults:

4a. "leak": ACTIVE wet release. One puddle plus a source on the drum.
- Source on the drum (its own "spill" mesh): realistically, liquid weeps from:
  - LLW: the lid bung or lid seal (a dark, wet trail running from the bung over the top chime and down the side), or a perforated bottom chime (wet darkening at the base).
  - ILW: the lid seam or vent filter (a wet trail down from the lid flange).
  The trail is 2–6 cm wide, darker than its surroundings, with a GLOSSY edge (roughness 0.05–0.15) and uniform tone. It is NOT orange (that distinguishes it from rust streaks). On LLW it ends in a dark wet band on the bottom 2–5 cm of the drum on the leak side.
- Puddle (its own "spill" mesh, 2 mm above the floor):
  - Shape: an irregular lobed outline (not a circle) that touches the drum base, elongated 1.5–2.5× in a seeded direction (the floor's slight fall toward a drain), 0.3–1.0 m long. Placed on the aisle-facing side where possible, so it can spread a little into the aisle (a real trip and contamination hazard).
  - Surface: like WET floor, not paint.
    - The centre is a darkened, slightly tinted version of the floor colour with very low roughness (0.02–0.08), so it clearly shows the overhead lights as reflections. This is the key realism cue.
    - The edges get rougher and lighter as the film thins.
    - A thin bright meniscus line at the wet edge.
  - Tint by category:
    - LLW: rust-tinged amber-brown leachate (the liquid picks up iron oxide from the corroding drum), strongest near the drum.
    - ILW: nearly clear, slightly milky grey leachate from the grout (high pH), with a thin WHITE crystalline crust forming at the edge.

4b. "residue": DRIED release evidence. No liquid, but signs that something leaked before. All class "spill":
- Floor stain (its own mesh): the same lobed outline style as a puddle, but MATTE (roughness 0.7–0.9). 2–4 concentric tide-mark rings (a darker or lighter crisp edge line at each ring, from repeated evaporation), with a slightly different shade inside each ring.
  - LLW: brown-orange dried stain with darker ring lines.
  - ILW: pale grey-white stain with a white powdery/crystalline crust (efflorescence: calcium carbonate from grout leachate) concentrated at the ring lines.
- Deposits on the drum (their own mesh):
  - ILW: white crystalline crust beads and short "stalactite" drips under the lid seam or vent filter, lumpy in the normal map.
  - LLW: dried dark run marks below the bung, with a light crust where they end.
  Matte, chalky (roughness 0.9).
Wet and dried states can be combined ("leak" + "residue" = an active leak on top of old tide marks).

Prim paths: /World/Defects/D07/Spill_0, Spill_1, ... (puddle, trail, residue and deposits are separate meshes).

✅ Check: show close-ups of an LLW leak, an ILW leak, an LLW residue and an ILW residue. The wet ones must clearly reflect the lights. The dried ones must look dry and show tide-mark rings. Neither should look like paint.

----------------------------------------------------------------------
STEP 5: Bulging, dents, obstruction and internal corrosion
----------------------------------------------------------------------
5a. "bulge" (time-box 30 min). Rebuild the drum Body with a deformed profile:
- LLW: the lid domes upward 15–40 mm at the centre, the top chime tilts outward and looks distorted, and the sides barrel outward with the radius increasing 2–5% at mid-height (smooth). The rolling hoops are stretched (less pronounced). Optionally, fine crazing cracks in the paint on the domed lid.
- ILW: the lid domes 10–30 mm, and the body swells 1–3% in the upper third near the lid seam. The stainless reflections should visibly warp across the bulge, a natural visual cue.
Record the actual "shape": {"max_radius": ..., "lid_rise": ...}. The class stays "drum" (the box naturally gets slightly bigger). No new YOLO class: the robot detects bulging by comparing depth or silhouette against the nominal radius/height in drums.json.

5b. "dent": a localised inward dent (handling impact), 15–25 cm wide and 2–5 cm deep, at 30–70% height on a seeded side, made by displacing vertices of the Body mesh with a smooth falloff. On LLW the paint is creased at the dent with a few cracks (cosmetic only, unless "corrosion" is also present). Recorded in "shape.dents". No class.

5c. "obstructed": obstruct_drum(drum_id, kind, seed). Place a realistic object 0.3–0.6 m in front of the drum's aisle-facing side, hiding 60–100% of that face from the aisle. Kinds (simple primitives, unlabelled, under /World/Obstructions/):
- "pallet_stack": 3–5 stacked wooden pallets (slatted boxes)
- "trolley": a yellow drum-handling trolley with a handle
- "shield_blocks": a low wall of grey interlocking shielding blocks
- "pvc_sheet": a hanging translucent PVC contamination barrier on a simple frame
It must NOT block the aisle (stay within the drum band or the first 0.3 m of the aisle). Set "obstructed": true. The robot should end up reporting "Couldn't inspect" for this drum.

5d. "internal_corrosion": ONLY sets "internal_corrosion": true in drums.json. No visual. It can be combined with a mild "bulge" (lid_rise ≤ 15 mm) to represent a possible early outward sign. This exists so we can show the robot honestly reporting what a camera cannot see.

✅ Check: side-by-side views of a normal vs bulged LLW drum and a normal vs bulged ILW drum (the difference should be visible but not cartoonish), one dented drum, and one drum hidden behind each obstruction kind.

----------------------------------------------------------------------
STEP 6: Semantic labels (CRITICAL: the training data depends on this)
----------------------------------------------------------------------
Use this version's semantics labelling API (check its name; it changed between versions). Each labelled prim gets TWO semantic types:
- type "class": the drum Body gets "drum", each corrosion mesh gets "corrosion", each spill mesh (puddle, trail, residue, deposits) gets "spill"
- type "drum_id": the ID of the drum it belongs to, e.g. "D07" (on the body AND on all its defects)
Everything else gets NO class: label plates, lids (unless included in the drum, see below), walls, floor, markings, signs, equipment, obstructions and the robot.
Prefer labelling the whole visible drum (body + lid parts) "drum" so the box covers the full drum. Tell me which you chose.

Then prove it with test_render.py. For each case below:
- Place a camera 2 m in front of the drum at 0.6 m height, tilted 10° down, at 640×640.
- Use Replicator to render ONE frame and save the RGB image plus 2D tight bounding boxes (semantic type "class"), with the drum_id for each box.
- Draw the boxes on the image with class + drum_id text and save it as sim/out/test_render/<case>_boxes.png.
- Print the box list.
Cases:
(a) LLW drum, faults ["corrosion", "leak"], severity 3
(b) ILW drum, faults ["corrosion", "residue"], severity 2
(c) bulged LLW drum, clean
(d) obstructed drum (pallet_stack)

✅ Check: tight, correct boxes around the drum, each corrosion feature and each spill feature. Nothing around the plates, floor markings, wheel marks, heat tint or obstructions. In case (d), the drum box covers only the visible part (or is missing if fully hidden; tell me which Replicator does).

----------------------------------------------------------------------
STEP 7: Robot dog and move_to
----------------------------------------------------------------------
- Load one of this version's built-in quadrupeds (Spot, ANYmal or a Unitree model). Spawn it at (1.0, 6.0) facing +x.
- move_to(x, y) must be NON-BLOCKING. It sets a goal and returns immediately. A physics/update callback moves the robot each tick. is_moving() and get_pose() -> (x, y, yaw) report status. A blocking loop would freeze the viewer and the sim, so don't use one.
- Navigation: plan a path over the aisles.json waypoint graph (a simple shortest path is fine), skipping blocked waypoints (see block_aisle), so the robot only travels along aisles and never passes through drums or obstructions. If the target point isn't on the graph, go to the nearest waypoint, then straight to the target if that's inside an aisle. If no path exists, stop and report "unreachable" via status().
- MODE = "slide" is the DEFAULT for the MVP: move the robot's root smoothly along the path (about 0.5 m/s, turning toward the direction of travel, legs in a standing pose, no physics on the legs). The whole team depends on move_to working, so make this one solid first.
- MODE = "walk" (optional, time-box 45 min): use the built-in walking policy, driven by velocity commands toward the next waypoint. If it's unreliable, say so, leave it switched off behind the flag, and move on.

✅ Check: the dog moves to 3 different points (e.g. (6.0, 2.0), (14.0, 6.0), (18.75, 10.0)) without going through drums, and is_moving() turns false when it arrives.

----------------------------------------------------------------------
STEP 8: Cameras on the dog
----------------------------------------------------------------------
Attach to the dog's body (as child prims, so they move with it):
- an RGB camera and a depth camera at the same pose: 0.6 m above the floor, facing forward, tilted 10° down, 640×640, a realistic wide-ish lens (about 70–90° horizontal field of view).
capture_frame(out_dir) saves:
- rgb_XXXX.png
- depth_XXXX.npy (float32, metres)
- meta_XXXX.json: robot pose (x, y, yaw), camera world position and rotation, camera intrinsics (fx, fy, cx, cy, width, height), sim time.

✅ Check: a saved frame shows the drums from the dog's point of view, the depth values look sensible (about 1–5 m to nearby drums), and a bulged drum's depth profile visibly differs from a normal one's.

----------------------------------------------------------------------
STEP 9: Demo layout and events
----------------------------------------------------------------------
layouts/layout_demo.json, a fixed scenario that shows every fault type. Defects are on aisle-facing sides, in both zones:
{"seed": 42,
 "drums": {
   "D03": {"faults": ["corrosion"], "severity": 2},
   "D06": {"faults": ["residue"]},
   "D10": {"faults": ["corrosion", "leak"], "severity": 3},
   "D11": {"faults": ["internal_corrosion"]},
   "D14": {"faults": ["obstructed", "corrosion"], "severity": 1, "obstruction": "pallet_stack"},
   "D20": {"faults": ["corrosion"], "severity": 1},
   "D22": {"faults": ["bulge"]},
   "D25": {"faults": ["corrosion", "residue"], "severity": 2},
   "D27": {"faults": ["leak"]},
   "D18": {"faults": ["dent"]}
 },
 "robot_start": [1.0, 6.0, 0.0]}
(All other drums are clean. D14 is corroded BEHIND the obstruction, which tests whether the robot honestly reports "Couldn't inspect". D11 has hidden internal corrosion that a camera cannot detect. D06 and D10 face each other across aisle 2.)
load_layout(path) rebuilds the scene exactly: same defects, same shapes, same textures, same obstructions.

Prepare (but don't trigger) mid-run events in events.py. Each is a function that works WHILE the sim is running:
- start_leak(drum_id, seed=0): adds "leak" to that drum. The wet trail appears, and the puddle grows from 20% to 100% scale over about 5 s. Labels it "spill" + drum_id and updates drums.json.
- block_aisle(aisle_number, x=None): places a realistic obstruction (a yellow steel pallet stillage, or 2 stacked crates with yellow/black hazard tape) across the aisle at x (default: the aisle's middle in the LLW zone). No semantic class. Marks the covered waypoints as blocked (exposed through get_blocked()) so move_to re-routes around them.
- obstruct_drum(drum_id, kind) from Step 5c must also work mid-run.

✅ Check: load_layout gives the same scene every time (render the same frame twice and compare the images), and all three events work while the sim is running.

----------------------------------------------------------------------
STEP 10: Save and document
----------------------------------------------------------------------
- Save the demo scene as sim/scene_demo.usd (textures referenced by relative path).
- README.md with EXACT commands to:
  - launch Isaac Sim with livestream
  - build the hall
  - load the demo layout
  - move the dog
  - save a camera frame
  - trigger each event
  - change a drum's faults
- Include the fault taxonomy table from section 2 and the drums.json schema.
- List known limitations and anything you dropped because of the time limits.

======================================================================
8. DELIVERABLES
======================================================================
- The scripts above
- drums.json, aisles.json, layouts/layout_demo.json
- sim/scene_demo.usd
- sim/out/test_render/ (the Step 6 proof images)
- README.md

======================================================================
9. NOT NOW (later tasks; just keep the code easy to extend)
======================================================================
- The radiation simulation (only store source_strength now)
- Mass training-image generation and domain randomisation. But DO make sure: lights are findable by path, fault builders take a seed and expose colour/size/count/severity parameters, and the texture bank can be extended.
- Connecting to the agent and the dashboard (no servers, ROS or networking yet)
- Stacking drums, stillages, multi-tier storage
- Physically simulated liquid (puddles are static meshes that can scale)
- Walking-policy tuning beyond the 45-minute time box
