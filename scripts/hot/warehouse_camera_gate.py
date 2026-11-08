"""Capture review stills at spawn and the first stop before adding inference."""
from PIL import Image
from pxr import Gf


def gate_view(camera, eye, target, focal):
    transform = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
    q = transform.GetInverse().ExtractRotationQuat()
    camera.prim.GetAttribute('focalLength').Set(focal)
    camera.set_world_pose(position=np.array(eye), orientation=np.array([q.GetReal(), *q.GetImaginary()]),
                          camera_axes='usd')


def capture_pair(label):
    for _ in range(12):
        world.render()
    for name, camera in (('chase', chase), ('onboard', onboard)):
        frame = camera.get_rgba()
        if frame is None or not frame.size:
            raise RuntimeError(f'{label} {name} returned no pixels')
        Image.fromarray(frame[:, :, :3].astype(np.uint8)).save(OUT / f'{label}-{name}.png')


target = inspection_targets(warehouse_map)['A-L-01-T1']
route = route_from_spawn(warehouse_map, target['stop'])
try:
    gate_view(chase, (2.3, 5.0, 1.6), (1.0, 6.0, 0.45), 22.5)
    gate_view(onboard, (1.35, 6.0, 0.68), (1.55, 4.85, 0.55), 22.5)
    capture_pair('spawn')
    result = walk(route, name='gate_walk', max_s=20, speed=0.4)
    if not result['reached']:
        raise RuntimeError('First inspection stop was not reached')
    x, y = result['final_xy']
    # The chase camera stays within the open aisle, looking across it.
    gate_view(chase, (x - 0.95, y - 0.85, 1.5), (x + 0.4, y + 0.8, 0.6), 20.0)
    gate_view(onboard, (x, y + 0.35, 0.68), tuple(target['centre']), 22.5)
    capture_pair('inspection')
finally:
    for camera in (chase, onboard):
        camera.prim.GetAttribute('focalLength').Set(15.0)
