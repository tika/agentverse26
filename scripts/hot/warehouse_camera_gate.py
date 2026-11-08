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
    result = walk(route, name='gate_walk', max_s=20, speed=0.4, final_yaw=target['yaw'])
    if not result['ready_for_capture']:
        raise RuntimeError('Spot did not reach and hold the inspection heading')
    x, y = result['final_xy']
    # The chase camera stays within the open aisle, looking across it.
    gate_view(chase, (x - 1.15, y - 1.05, 1.65), (x + 0.25, y + 0.45, 0.55), 16.0)
    # Keep the camera aligned to the actual final body heading.
    onboard.prim.GetAttribute('focalLength').Set(15.0)
    (OUT / 'inspection_stop.json').write_text(json.dumps(result, indent=2) + '\n')
    capture_pair('inspection')
finally:
    for camera in (chase, onboard):
        camera.prim.GetAttribute('focalLength').Set(15.0)
