"""Run-scoped warehouse coverage derived from accepted onboard evidence."""

from collections import Counter
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class WarehouseObservations:
    """Keep per-package evidence independent of the robot's progress along a route."""

    def __init__(self, path, run_id, package_ids):
        self.path = Path(path)
        self.run_id = run_id
        self.packages = {package_id: {} for package_id in package_ids}
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved["run_id"] != run_id or saved["packages"].keys() != self.packages.keys():
                raise ValueError("Checkpoint belongs to a different mission")
            self.packages = saved["packages"]

    def accept(self, package_id, frame_id, *, view, finding):
        """Record a frame after the caller verifies identity and capture quality."""
        frames = self.packages[package_id]
        evidence = {"view": view, "finding": finding}
        if frame_id in frames:
            if frames[frame_id] != evidence:
                raise ValueError(f"Conflicting evidence for {package_id} in {frame_id}")
            return
        frames[frame_id] = evidence

    def coverage(self, package_id):
        views = {evidence["view"] for evidence in self.packages[package_id].values()}
        if not views:
            return "unseen"
        return "inspected" if {"front", "oblique"} <= views else "seen"

    def counts(self):
        return dict(Counter(self.coverage(package_id) for package_id in self.packages))

    def checkpoint(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"run_id": self.run_id, "packages": self.packages}, indent=2)
        with NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
