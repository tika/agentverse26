"""Inspect the bundled Spot render meshes before recording a mission."""
import json
from pxr import Usd,UsdGeom

root=stage.GetPrimAtPath('/World/WalkingSpot')
stage.Load(root.GetPath())
rows=[]
for prim in Usd.PrimRange(root,Usd.TraverseInstanceProxies()):
    if prim.IsA(UsdGeom.Imageable):
        geom=UsdGeom.Imageable(prim)
        if prim.IsA(UsdGeom.Mesh) or geom.GetVisibilityAttr().Get()=='invisible' or geom.ComputePurpose()!='default':
            rows.append(dict(path=str(prim.GetPath()),type=prim.GetTypeName(),purpose=geom.ComputePurpose(),
                visibility=geom.ComputeVisibility(),authored_visibility=geom.GetVisibilityAttr().Get(),
                instance_proxy=prim.IsInstanceProxy(),loaded=prim.IsLoaded(),
                points=len(UsdGeom.Mesh(prim).GetPointsAttr().Get() or []) if prim.IsA(UsdGeom.Mesh) else None))
(OUT/'robot_visuals.json').write_text(json.dumps(dict(root_loaded=root.IsLoaded(),rows=rows),indent=2))
still((1.4,4.8,1.3),(3.0,6.0,.45),name='robot_before',focal=24)
print('[hot] robot visual probe '+json.dumps(dict(meshes=sum(r['type']=='Mesh' for r in rows),
    visible_meshes=sum(r['type']=='Mesh' and r['visibility']=='inherited' for r in rows),
    nondefault_purposes=sorted(set(r['purpose'] for r in rows)))),flush=True)
