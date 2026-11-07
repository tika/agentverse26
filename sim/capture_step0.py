"""Step 0 only: a fixed camera and one saved image of the hello-world cube."""
import importlib
import json
from pathlib import Path


def capture_cube(app, stage):
    import omni.replicator.core as rep
    from pxr import Gf, UsdGeom
    from isaacsim.core.experimental.utils.semantics import add_labels, get_labels

    output = Path(__file__).resolve().parent / 'out' / 'step0'
    output.mkdir(parents=True, exist_ok=True)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    cube = stage.GetPrimAtPath('/World/Cube')
    UsdGeom.Gprim(cube).CreateDisplayColorAttr([Gf.Vec3f(0.1, 0.45, 0.85)])
    add_labels(cube, labels=['cube'], taxonomy='class')
    add_labels(cube, labels=['STEP0'], taxonomy='test_id')
    labels = get_labels(cube)
    assert labels['class'] == ['cube'] and labels['test_id'] == ['STEP0']

    ground = UsdGeom.Cube.Define(stage, '/World/Ground')
    UsdGeom.Xformable(ground).AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.55))
    UsdGeom.Xformable(ground).AddScaleOp().Set(Gf.Vec3f(8, 8, 0.05))
    camera = UsdGeom.Camera.Define(stage, '/World/Camera')
    pose = Gf.Matrix4d().SetLookAt(Gf.Vec3d(3, -4, 2), Gf.Vec3d(0, 0, 0), Gf.Vec3d(0, 0, 1))
    UsdGeom.Xformable(camera).AddTransformOp().Set(pose.GetInverse())
    camera.CreateFocalLengthAttr(24)
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(27)

    imports = {}
    for name in ('isaacsim.core.experimental.utils.stage', 'isaacsim.sensors.camera',
                 'isaacsim.robot.policy.examples.bundled.spot',
                 'isaacsim.robot.policy.examples.bundled.anymal'):
        module = importlib.import_module(name)
        imports[name] = str(module.__file__)
    (output / 'runtime_checks.json').write_text(json.dumps({'imports': imports, 'labels': labels}, indent=2))
    stage.Export(str(output / 'cube.usda'))

    product = rep.create.render_product('/World/Camera', (640, 480))
    writer = rep.WriterRegistry.get('BasicWriter')
    writer.initialize(output_dir=str(output), rgb=True)
    writer.attach([product])
    for _ in range(20):
        app.update()
    rep.orchestrator.run(num_frames=1)
    for _ in range(600):
        app.update()
        if list(output.glob('rgb*.png')) and rep.orchestrator.get_is_stopped():
            break
    rep.orchestrator.stop()
    rep.orchestrator.wait_until_complete()
    images = list(output.glob('rgb*.png'))
    if not images:
        raise RuntimeError('BasicWriter produced no PNG; Step 0 is not visually verified.')
    writer.detach()
    print(f'STEP0_CAPTURE_OK {images[0]}', flush=True)
