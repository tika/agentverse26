"""Runtime asset map: what perception/policy may know about the store (audit A1).

The runtime may know immutable IDs, printed plate text (display_id), nominal
dimensions, declared category, nominal pose and the location map. It may NOT
know faults, defects, actual deformed shape, source parameters, appearance seeds
or USD prim paths (which would allow reading simulator-only attributes).

This module uses an ALLOW-list: any field not listed here is rejected on load,
so new truth fields added to sim/drums.json can never leak by default.
"""
import json
import math
from pathlib import Path

MAP_VERSION = "1.0.0"

ALLOWED_FIELDS = {
    "id",            # immutable D01..; never re-used
    "legacy_id",     # original D01-D28 association (same as id for originals)
    "display_id",    # text printed on the plate, e.g. "A03" (NOT the immutable id)
    "category",      # declared LLW / ILW
    "x", "y",        # nominal centre, metres, world frame, Z up
    "yaw",           # nominal yaw, radians (normalise at use)
    "radius", "height",  # nominal dimensions, metres
    "row", "zone", "facing_aisle",
    "location",      # stage-2 location block (lane/side/column/tier/... per contracts)
    "stack_id", "base_z",
}
REQUIRED_FIELDS = ("id", "display_id", "category", "x", "y", "radius", "height")

# Known simulator-truth fields, used only to give a helpful error message.
KNOWN_TRUTH_FIELDS = {"faults", "defects", "state", "corrosion_severity", "internal_corrosion",
                      "obstructed", "shape", "source_strength", "appearance_seed", "scene_seed",
                      "prim_path", "paint_color"}


def runtime_view(inventory_entries):
    """Pure function: strip a simulator inventory down to the runtime map.

    Codex owns emitting the map file; this helper lets both sides produce the
    same thing and is what the tests use against sim/drums.json.
    """
    drums = []
    for e in inventory_entries:
        d = {k: e[k] for k in ALLOWED_FIELDS if k in e}
        d.setdefault("legacy_id", e["id"])
        drums.append(d)
    return {"map_version": MAP_VERSION, "drums": drums}


def map_errors(runtime_map):
    errors = []
    if runtime_map.get("map_version") != MAP_VERSION:
        errors.append(f"map_version must be {MAP_VERSION}")
    extra_top = set(runtime_map) - {"map_version", "drums", "source", "generated_s"}
    if extra_top:
        errors.append(f"unexpected top-level fields {sorted(extra_top)}")
    seen_ids, seen_display = set(), {}
    for i, d in enumerate(runtime_map.get("drums", [])):
        w = f"drums[{i}]({d.get('id')}): "
        leaked = set(d) - ALLOWED_FIELDS
        if leaked:
            truth = sorted(leaked & KNOWN_TRUTH_FIELDS)
            errors.append(w + (f"simulator truth fields not allowed: {truth}" if truth
                               else f"fields not in runtime allow-list: {sorted(leaked)}"))
        for k in REQUIRED_FIELDS:
            if k not in d:
                errors.append(w + f"missing '{k}'")
        for k in ("x", "y", "radius", "height"):
            if k in d and not (isinstance(d[k], (int, float)) and math.isfinite(d[k])):
                errors.append(w + f"'{k}' must be finite")
        if d.get("id") in seen_ids:
            errors.append(w + "duplicate immutable id")
        seen_ids.add(d.get("id"))
        if d.get("display_id") in seen_display:
            errors.append(w + f"display_id duplicates {seen_display[d['display_id']]}")
        seen_display[d.get("display_id")] = d.get("id")
    return errors


def load_runtime_map(path):
    """Load and validate; refuses files containing any non-allowed field."""
    runtime_map = json.loads(Path(path).read_text())
    if isinstance(runtime_map, list):
        raise ValueError("this looks like a raw simulator inventory (list); load a runtime map instead")
    errors = map_errors(runtime_map)
    if errors:
        raise ValueError("invalid runtime asset map: " + "; ".join(errors[:5]))
    return runtime_map


def display_id_collisions(runtime_map):
    """Plate texts that are also some OTHER drum's immutable id (e.g. plate 'D06' on D27).

    A reader that treats plate text as an immutable id would mis-identify these.
    """
    ids = {d["id"] for d in runtime_map["drums"]}
    return sorted((d["display_id"], d["id"]) for d in runtime_map["drums"]
                  if d["display_id"] in ids and d["display_id"] != d["id"])
