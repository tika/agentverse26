"""One Replicator pass: RGB, metric depth, tight boxes and stable YOLO class IDs."""
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

CLASSES={'drum':0,'corrosion':1,'spill':2}


def camera(stage,path,eye,target,focal=24,resolution=(640,640)):
    from pxr import Gf,UsdGeom
    result=UsdGeom.Camera.Define(stage,path)
    pose=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse()
    xform=UsdGeom.Xformable(result)
    xform.ClearXformOpOrder()
    xform.AddTransformOp().Set(pose)
    result.CreateFocalLengthAttr(focal)
    result.CreateHorizontalApertureAttr(36)
    result.CreateVerticalApertureAttr(36*resolution[1]/resolution[0])
    result.CreateClippingRangeAttr((.05,40))
    return str(result.GetPath())


def attach_capture(stage,name,path,output,resolution=(640,640)):
    import omni.replicator.core as rep
    directory=Path(output)/name
    directory.mkdir(parents=True,exist_ok=True)
    writer=rep.WriterRegistry.get('BasicWriter')
    writer.initialize(output_dir=str(directory),rgb=True,distance_to_image_plane=True,
                      bounding_box_2d_tight=True,semantic_types=['class','drum_id'])
    product=rep.create.render_product(path,resolution)
    writer.attach([product])
    return writer,directory


def finish_captures(app,captures,warmup=30):
    import omni.replicator.core as rep
    for _ in range(warmup): app.update()
    rep.orchestrator.run(num_frames=1)
    for _ in range(900):
        app.update()
        if all(list(directory.rglob('rgb*.png')) for _,directory in captures) and rep.orchestrator.get_is_stopped(): break
    rep.orchestrator.stop(); rep.orchestrator.wait_until_complete()
    for writer,_ in captures: writer.detach()
    return {directory.name:export_boxes(directory) for _,directory in captures}


def export_boxes(directory):
    directory=Path(directory)
    rgb=next(directory.rglob('rgb*.png'))
    data=np.load(next(directory.rglob('bounding_box_2d_tight_*.npy')),allow_pickle=False)
    labels_path=next(directory.rglob('bounding_box_2d_tight_labels*.json'))
    labels=json.loads(labels_path.read_text())
    labels=labels.get('idToLabels',labels)
    image=Image.open(rgb).convert('RGB'); draw=ImageDraw.Draw(image)
    pixels=np.asarray(image)
    assert pixels.mean()>3 and np.percentile(pixels,99)>15, 'Black/invalid RGB frame; do not use for training'
    width,height=image.size
    boxes=[]; yolo=[]
    colors={'drum':(60,220,90),'corrosion':(255,120,35),'spill':(70,190,255)}
    for row in data:
        semantic=labels.get(str(int(row['semanticId'])),{})
        cls=semantic.get('class'); drum=semantic.get('drum_id')
        if isinstance(cls,list): cls=cls[0]
        if isinstance(drum,list): drum=drum[0]
        # Replicator normalises semantic values to lowercase; inventory IDs are uppercase.
        if isinstance(drum,str): drum=drum.upper()
        assert cls in CLASSES,semantic
        assert drum and drum.startswith('D'),semantic
        x0,y0,x1,y1=[int(row[key]) for key in ('x_min','y_min','x_max','y_max')]
        if x1<=x0 or y1<=y0: continue
        assert 0<=x0<width and 0<=y0<height and x1<=width and y1<=height,(x0,y0,x1,y1)
        box={'class':cls,'drum_id':drum,'xyxy':[x0,y0,x1,y1]}
        boxes.append(box)
        draw.rectangle((x0,y0,x1,y1),outline=colors[cls],width=2)
        text=f'{cls} {drum}'; text_y=max(0,y0-13)
        draw.rectangle((x0,text_y,x0+len(text)*7,text_y+13),fill=(15,15,15))
        draw.text((x0+1,text_y),text,fill=colors[cls])
        yolo.append(f'{CLASSES[cls]} {(x0+x1)/2/width:.7f} {(y0+y1)/2/height:.7f} {(x1-x0)/width:.7f} {(y1-y0)/height:.7f}')
    image.save(directory/'boxes.png')
    (directory/'boxes.json').write_text(json.dumps(boxes,indent=2)+'\n')
    (directory/'labels.txt').write_text('\n'.join(yolo)+'\n')
    return {'rgb':str(rgb.name),'box_count':len(boxes),'boxes':boxes,
            'resolution':[width,height],'depth_units':'metres'}
