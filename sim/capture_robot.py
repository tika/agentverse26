"""Load the checked layout and bundled Spot; prove child camera outputs in the hall."""
import json
import math
from pathlib import Path
SIM=Path(__file__).resolve().parent
OUTPUT=SIM/'out/robot'

if __name__=='__main__':
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'renderer':'MinimalRendering','minimal_shading_mode':1})
    import omni.usd
    from layouts import load_layout
    from robot import load_robot,attach_cameras,capture_frame
    from training_capture import camera,attach_capture,finish_captures
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context=omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_robot.usda'))
    context.open_stage(str(SIM/'scene_robot.usda'))
    load_layout()
    stage=context.get_stage()
    robot=load_robot((4.5,5.5,.55),math.pi/2)
    for _ in range(20):app.update()
    mounted=attach_cameras(robot['body'])
    report={'robot':robot,'camera':mounted,'frame':capture_frame(OUTPUT,app)}
    path=camera(stage,'/World/ReviewCameras/dog_overview',(1.5,3.8,2.4),(4.5,5.5,.6),23,(960,640))
    report['third_person']=finish_captures(app,[attach_capture(stage,'dog_overview',path,OUTPUT,(960,640))])
    stage.GetRootLayer().Save()
    (OUTPUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('ROBOT_CAPTURE_OK',json.dumps(report),flush=True)
    app.close(wait_for_replicator=False)
