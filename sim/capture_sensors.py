"""RTX RGB/depth proof + scalar sensor packet, preserving the canonical 28 drums."""
import json
from pathlib import Path
SIM = Path(__file__).resolve().parent
OUTPUT = SIM/'out/sensors'

if __name__ == '__main__':
    from isaacsim import SimulationApp
    app = SimulationApp({'headless':True,'renderer':'RayTracedLighting'})
    import omni.usd
    import omni.replicator.core as rep
    import numpy as np
    from PIL import Image
    from build_hall import build_scene
    from capture_hall import capture_views, check_scene
    from capture_drums import check_drums
    from sensors import create_sensor_rig, SensorWorld, load_config
    from criteria import safety_decision
    OUTPUT.mkdir(parents=True,exist_ok=True)
    context = omni.usd.get_context()
    context.get_stage().GetRootLayer().Export(str(SIM/'scene_sensors.usda'))
    context.open_stage(str(SIM/'scene_sensors.usda'))
    build = build_scene(42)
    stage = context.get_stage()
    entries = json.loads((SIM/'drums.json').read_text())
    check_drums(stage,entries)
    checks = check_scene(stage,28)
    eye, target = (12,1.9,.85), (12,3.45,.6)
    path = create_sensor_rig(stage,eye,target)
    product = rep.create.render_product(path,tuple(load_config()['camera']['resolution']))
    writer = rep.WriterRegistry.get('BasicWriter')
    writer.initialize(output_dir=str(OUTPUT/'rgb_depth'),rgb=True,
                      distance_to_image_plane=True,distance_to_camera=True)
    writer.attach([product])
    views = capture_views(app,stage,{
        'overview':((1.2,1.5,4.6),(12,6,1.5),20),
        'llw_closeup':((3,1.95,1.2),(3,3.45,.44),32),
        'ilw_closeup':((12,1.4,1.6),(12,3.45,.6),30)},OUTPUT)
    writer.detach()
    rgb = list((OUTPUT/'rgb_depth').rglob('rgb*.png'))
    planes = list((OUTPUT/'rgb_depth').rglob('distance_to_image_plane*.npy'))
    ranges = list((OUTPUT/'rgb_depth').rglob('distance_to_camera*.npy'))
    assert rgb and planes and ranges, 'Missing real RTX sensor outputs'
    depth = np.load(planes[0]).squeeze()
    radial = np.load(ranges[0]).squeeze()
    assert depth.shape == (480,640) and radial.shape == depth.shape
    valid = np.isfinite(depth) & (depth > 0)
    assert valid.mean() > .5 and np.std(depth[valid]) > .1
    # Preview only: brighter = nearer, black = invalid. Raw metric NPY is authoritative.
    grey = np.where(valid,255*(1-np.clip(depth/8,0,1)),0).astype(np.uint8)
    Image.fromarray(grey).save(OUTPUT/'depth_preview.png')
    # This ROI illustrates a depth measurement; general obstacle segmentation comes later.
    centre = radial[200:280,280:360]
    roi_distance = float(np.min(centre[np.isfinite(centre) & (centre>0)]))
    world = SensorWorld(entries)
    observation = {**world.sample(eye,0),'camera_timestamp_s':0,
                   'rgb_file':str(rgb[0].relative_to(OUTPUT)),
                   'depth_plane_m_file':str(planes[0].relative_to(OUTPUT)),
                   'depth_range_m_file':str(ranges[0].relative_to(OUTPUT))}
    (OUTPUT/'agent_observation.json').write_text(json.dumps(observation,indent=2)+'\n')
    # A separate illustrative rule invocation; ROI distance isn't a validated all-scene nearest-drum estimator.
    decision = safety_decision({**observation,'nearest_drum_surface_m':roi_distance},0)
    report = {'build':build,'checks':checks,'views':views,
              'sensor_camera':{'path':path,'eye':eye,'target':target,'resolution':[640,480]},
              'depth':{'units':'metres','valid_fraction':float(valid.mean()),
                       'min_m':float(depth[valid].min()),'max_m':float(depth[valid].max()),
                       'centre_roi_min_range_m':roi_distance},
              'example_rule_decision':decision,
              'limits':['Stationary rig; dog and locomotion not added yet',
                        'No trained visual detector/OCR; no fault condition inferred from these images',
                        'Scalar radiation model is illustrative, not physical radiation transport',
                        'ROI range is a demonstration, not a general obstacle-distance estimator']}
    stage.GetRootLayer().Save()
    (OUTPUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('SENSOR_CAPTURE_OK',json.dumps(report),flush=True)
    app.close(wait_for_replicator=False)
