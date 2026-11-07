"""Build Step 1 twice, validate it, and save four real Isaac camera renders."""
import hashlib
import json
from pathlib import Path

SIM = Path(__file__).resolve().parent
OUTPUT = SIM / 'out' / 'step1'
VIEWS = {
    'front_overview': ((1.2,1.5,4.6),(12,6,1.8),20),
    'rear_overview': ((18.8,10.5,3.8),(5,5.8,2.0),20),
    'entrance_detail': ((5.5,7.8,2.4),(.1,4.8,2.0),23),
    'aisle2': ((1.0,6.0,1.2),(15,6,1.2),21),
}


def check_scene(stage):
    from pxr import UsdGeom, UsdLux
    meshes = [prim for prim in stage.Traverse() if prim.IsA(UsdGeom.Mesh)]
    for prim in meshes:
        geom = UsdGeom.Mesh(prim)
        uv = UsdGeom.PrimvarsAPI(prim).GetPrimvar('st')
        assert uv and len(uv.Get()) == len(geom.GetFaceVertexIndicesAttr().Get()), prim.GetPath()
    lights = [prim for prim in stage.Traverse() if prim.IsA(UsdLux.RectLight)]
    assert len(lights) == 8
    values = [UsdLux.RectLight(prim).GetIntensityAttr().Get() for prim in lights]
    assert sorted(values) == [1800.0] + [4500.0]*7
    assert not any('LabelsAPI:' in schema or 'SemanticsAPI:' in schema
                   for prim in stage.Traverse() for schema in prim.GetAppliedSchemas())
    for path in ('Drums','Defects','Obstructions'):
        assert not stage.GetPrimAtPath('/World/'+path).GetChildren()
    assets = []
    for prim in stage.Traverse():
        attribute = prim.GetAttribute('inputs:file')
        if attribute:
            asset = attribute.Get().path
            assert not Path(asset).is_absolute(), asset
            assert (SIM/asset).exists(), asset
            assets.append(asset)
    return {'mesh_count':len(meshes),'all_meshes_have_uvs':True,
            'rect_lights':len(lights),'hall_has_no_semantic_classes':True,
            'relative_texture_references':len(assets),'empty_drums_defects_obstructions':True}


def prepare_view(stage, name, eye, target, focal):
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom
    output = OUTPUT/name
    output.mkdir(parents=True,exist_ok=True)
    path = '/World/ReviewCameras/'+name
    camera = UsdGeom.Camera.Define(stage,path)
    pose = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1))
    UsdGeom.Xformable(camera).AddTransformOp().Set(pose.GetInverse())
    camera.CreateFocalLengthAttr(focal)
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(22.5)
    product = rep.create.render_product(path,(1024,640))
    writer = rep.WriterRegistry.get('BasicWriter')
    writer.initialize(output_dir=str(output),rgb=True)
    writer.attach([product])
    return writer, {'eye':eye,'look_at':target,'focal_length_mm':focal}


if __name__ == '__main__':
    from isaacsim import SimulationApp
    app = SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    from build_hall import build_scene
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context = omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'hall.usda'))
    context.open_stage(str(SIM/'hall.usda'))
    first = build_scene(42)
    stage = context.get_stage()
    fingerprint = hashlib.sha256(stage.GetRootLayer().ExportToString().encode()).hexdigest()
    second = build_scene(42)
    assert fingerprint == hashlib.sha256(stage.GetRootLayer().ExportToString().encode()).hexdigest(), 'Rebuild changed the scene'
    assert first['build_seconds'] < 120 and second['build_seconds'] < 120
    report = {'first_build':first,'cached_build':second,'identical_rebuild':True,
              'scene_sha256':fingerprint,'checks':check_scene(stage),'views':{}}
    print('HALL_BUILD_OK',json.dumps(report),flush=True)
    import omni.replicator.core as rep
    writers = []
    for name,(eye,target,focal) in VIEWS.items():
        writer, report['views'][name] = prepare_view(stage,name,eye,target,focal)
        writers.append(writer)
    assert len({id(writer) for writer in writers}) == len(VIEWS)
    # One capture pass keeps exposure consistent across all render products.
    for _ in range(40): app.update()
    rep.orchestrator.run(num_frames=1)
    for _ in range(600):
        app.update()
        if all(list((OUTPUT/name).rglob('rgb*.png')) for name in VIEWS) and rep.orchestrator.get_is_stopped(): break
    rep.orchestrator.stop()
    rep.orchestrator.wait_until_complete()
    for writer in writers: writer.detach()
    for name in VIEWS:
        images = list((OUTPUT/name).rglob('rgb*.png'))
        assert images, f'No rendered image for {name}'
        report['views'][name]['image'] = str(images[0].relative_to(OUTPUT))
        print('VIEW_SAVED',name,images[0],flush=True)
    stage.GetRootLayer().Save()
    (OUTPUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('HALL_CAPTURE_OK',flush=True)
    app.close(wait_for_replicator=False)
