# Agentverse26 — nuclear-store robot inspection

Build the Isaac Sim environment one step at a time, following **MVP v2**.
Steps 0 and 1 are verified: Isaac Sim 6.2 rendered the cube and the empty,
textured 20 × 12 × 6 m hall on Modal and returned real camera screenshots.

- [Run commands, installed APIs and validation](sim/README.md)
- [Environment build specification](docs/environment_mvp.md)

Use Python 3.12+ locally. Review each step through exported screenshots/video,
as selected by the user; this replaces the specification's interactive-viewer
instructions. Stop after each step for review. Step 2, barrels, has not started.

All new project work belongs in this repository. Rendered outputs are stored
locally under `sim/out/` and ignored by Git. No credentials belong in the repo.
The small procedural texture bank and `sim/hall.usda` are tracked so the hall
can be opened with its relative texture references after cloning.
