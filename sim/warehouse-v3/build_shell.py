"""Write the v3 shell layer (/World/Hall) from map.json. Runs with usd-core or Isaac's python.

    python sim/v3/build_shell.py --map ../map.json --out ../shell.usda

The layer only authors /World/Hall (structure, roof, lights, wall details) so it composes as
a sublayer beside storage.usda (/World/Drums, /World/Racks) and the site layer (markings,
staging). Textures are written to <out dir>/assets/ and referenced relatively.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]


def build(map_path, out_path, seed=42):
    from pxr import Usd, UsdGeom
    from shell import build_shell
    layout = json.loads(Path(map_path).read_text())
    out_path = Path(out_path).resolve()
    stage = Usd.Stage.CreateNew(str(out_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, '/World')
    stage.SetDefaultPrim(world.GetPrim())
    report = build_shell(stage, layout, out_path.parent / 'assets', seed)
    stage.GetRootLayer().Save()
    report['meshes'] = sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))
    report['output'] = str(out_path)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--map', default=str(HERE.parents[2] / 'map.json'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(build(args.map, args.out, args.seed)))
