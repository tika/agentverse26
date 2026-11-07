# Probe: does semantic segmentation on the onboard camera return drum_id and class labels?
import json
import omni.replicator.core as rep
from PIL import Image

if 'seg' not in state:
    state['seg'] = rep.AnnotatorRegistry.get_annotator(
        'semantic_segmentation', init_params={'semanticTypes': ['class', 'drum_id'], 'colorize': False})
    state['seg'].attach([onboard.get_render_product_path()])
spot.restart_from_default_state(np.zeros(3, dtype=np.float32))
world.step(render=False)
position, _ = pose()
import math
from pxr import Gf
eye = position + np.array([0.47, 0, 0.22])
matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float, eye)), Gf.Vec3d(*map(float, eye + [1, 0.25, -0.15])), Gf.Vec3d(0, 0, 1))
quat = matrix.GetInverse().ExtractRotationQuat()
onboard.set_world_pose(position=eye, orientation=np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')
for _ in range(8):
    world.render()
data = state['seg'].get_data()
ids = np.asarray(data['data'])
labels = data['info']['idToLabels']
counts = {str(k): int((ids == int(k)).sum()) for k in labels}
(OUT / 'seg.json').write_text(json.dumps({'shape': list(ids.shape), 'labels': labels, 'counts': counts,
                                          'intrinsics': onboard.get_intrinsics_matrix().tolist()}, indent=1, default=str))
Image.fromarray(onboard.get_rgba()[:, :, :3].astype(np.uint8)).save(OUT / 'onboard.png')
print('[hot] seg labels', len(labels), flush=True)
