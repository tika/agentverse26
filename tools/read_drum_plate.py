"""Read a visible drum ID with a local Cosmos Reason 2 checkpoint."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
from spot_agent import CosmosPlanner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--box", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    args = parser.parse_args()
    planner = CosmosPlanner(args.model, None)
    print(json.dumps({"drum_id": planner.read_drum_plate(args.image, args.box)}))


if __name__ == "__main__":
    main()
