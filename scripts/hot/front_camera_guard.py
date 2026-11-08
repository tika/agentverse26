"""Audit the physical sensor mount on every frame, including already-warm workers."""
from front_camera import expected_world_pose,rotation
if not state.get('front_guard_installed'):
    _capture_primary=capture_front
    def capture_front(index,t):
        packet=_capture_primary(index,t)
        bp,bq=spot.articulation.get_world_poses()
        ep,er=expected_world_pose(bp.numpy().reshape(3),bq.numpy().reshape(4))
        cp,cq=onboard.get_world_pose(camera_axes='world')
        pe=float(np.linalg.norm(cp-ep));re=float(np.linalg.norm(rotation(cq)-er))
        if pe>.002 or re>.002:raise RuntimeError(f'Front mount failed: {pe:.6f} m, {re:.6f} rotation error')
        packet['info'].update(mount_position_error_m=pe,mount_rotation_error=re)
        return packet
    state['front_guard_installed']=True
