"""Associate an observed drum with an immutable ID, keeping uncertainty visible.

Inputs are observations only: a plate reading (text from OCR/Cosmos, or None) and
an estimated world position of the observed drum (from detection box + depth +
camera pose). The runtime asset map supplies nominal positions and plate texts.
Ground-truth fault state is never consulted.

Output is the contract identity block: {status, candidates, evidence, method}
with status in confirmed / ambiguous / unread / conflict (perception/contracts.py).
"""
import math
import re

PLATE_RE = re.compile(r"^[A-Z][0-9]{2}$")

DEFAULT_GATE_M = 0.6      # max distance from a nominal drum centre to accept it as a candidate
DEFAULT_MARGIN_M = 0.25   # second candidate must be this much farther for a unique geometric match


def _centre(d):
    base = d.get("base_z", (d.get("location") or {}).get("base_z_m", 0.0)) or 0.0
    return (d["x"], d["y"], base + d["height"] / 2)


def geometry_candidates(observed_xyz, runtime_map, gate_m=DEFAULT_GATE_M):
    """Drums whose nominal centre lies within gate_m of the observed position, nearest first.

    observed_xyz may be (x, y) for floor-level reasoning or (x, y, z) to separate stacked tiers.
    """
    if len(observed_xyz) not in (2, 3) or not all(math.isfinite(v) for v in observed_xyz):
        raise ValueError("observed position must be 2 or 3 finite metres")
    out = []
    for d in runtime_map["drums"]:
        c = _centre(d)[:len(observed_xyz)]
        dist = math.dist(observed_xyz, c)
        if dist <= gate_m:
            out.append((dist, d["id"]))
    return sorted(out)


def plate_to_id(plate_text, runtime_map):
    """Map printed plate text to an immutable ID via display_id ONLY."""
    if plate_text is None:
        return None
    matches = [d["id"] for d in runtime_map["drums"] if d["display_id"] == plate_text]
    return matches[0] if len(matches) == 1 else None


def associate(runtime_map, *, plate_text=None, observed_xyz=None, evidence_ids=(),
              gate_m=DEFAULT_GATE_M, margin_m=DEFAULT_MARGIN_M):
    evidence = list(evidence_ids)
    notes = []
    if plate_text is not None and not PLATE_RE.match(plate_text):
        notes.append(f"plate text {plate_text!r} malformed; ignored")
        plate_text = None
    plate_id = plate_to_id(plate_text, runtime_map)
    if plate_text is not None and plate_id is None:
        notes.append(f"plate text {plate_text!r} not in asset map")
    if plate_text is not None and any(d["id"] == plate_text for d in runtime_map["drums"]) and plate_id != plate_text:
        notes.append(f"plate text {plate_text!r} is a display_id, not immutable id {plate_text}")

    geo = geometry_candidates(observed_xyz, runtime_map, gate_m) if observed_xyz is not None else []
    geo_ids = [i for _, i in geo]
    unique_geo = geo_ids[0] if (len(geo) == 1 or (len(geo) > 1 and geo[1][0] - geo[0][0] >= margin_m)) else None

    def result(status, candidates, method):
        return {"status": status, "candidates": candidates, "evidence": evidence,
                "method": method, "notes": notes}

    if plate_id and observed_xyz is None:
        return result("confirmed", [plate_id], "plate_read")
    if plate_id and plate_id in geo_ids:
        return result("confirmed", [plate_id], "plate_read+geometry_map")
    if plate_id and geo_ids:
        # Readable plate somewhere unexpected: drum moved, or plate/box mis-association.
        notes.append("plate and position disagree; keep both until a second view resolves it")
        return result("conflict", [plate_id] + [i for i in geo_ids if i != plate_id], "plate_read+geometry_map")
    if plate_id:
        notes.append("plate read but no mapped drum near the observed position")
        return result("conflict", [plate_id, "unmapped_position"], "plate_read+geometry_map")
    if unique_geo:
        # Geometry alone is a provisional association, not a confirmation.
        return result("unread", [unique_geo], "geometry_map")
    if len(geo_ids) >= 2:
        return result("ambiguous", geo_ids, "geometry_map")
    return result("unread", [], "none")
