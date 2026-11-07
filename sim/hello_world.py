from isaacsim import SimulationApp
app = SimulationApp({'headless': True, 'renderer': 'RayTracedLighting'})
import omni.usd
from pxr import UsdGeom, UsdLux
stage = omni.usd.get_context().get_stage()
UsdGeom.Cube.Define(stage, '/World/Cube').CreateSizeAttr(1.0)
UsdLux.DomeLight.Define(stage, '/World/Light').CreateIntensityAttr(1000)
from capture_step0 import capture_cube
capture_cube(app, stage)
app.close(wait_for_replicator=False)
