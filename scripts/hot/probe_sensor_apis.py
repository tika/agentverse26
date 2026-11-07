# Probe: constructor/method signatures for the RTX LiDAR, IMU and joint-state sensors.
import inspect
import json
from isaacsim.sensors.rtx import LidarRtx
from isaacsim.sensors.experimental.physics import IMUSensor, JointStateSensor

report = {}
for cls in (LidarRtx, IMUSensor, JointStateSensor):
    entry = {'init': str(inspect.signature(cls.__init__)), 'doc': (cls.__doc__ or '')[:1500], 'methods': {}}
    for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
        if not name.startswith('_'):
            try:
                entry['methods'][name] = str(inspect.signature(fn))
            except Exception:
                entry['methods'][name] = '?'
    report[cls.__name__] = entry
(OUT / 'signatures.json').write_text(json.dumps(report, indent=1))
print('[hot] probe done', flush=True)
