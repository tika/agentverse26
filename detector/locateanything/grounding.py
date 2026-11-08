"""Parse NVIDIA's normalized grounding tokens; no detector scores are invented."""
import re

MODEL_ID='nvidia/LocateAnything-3B'
REVISION='c32291ca5e996f5a7a485845b4f57a233936bba0'
PROMPT=('Locate all the instances that matches the following description: '
        'metal drum</c>rusty metal drum</c>metal drum with a bulging lid or swollen sides.')
PROMPTS=(
    'Locate all the instances that match the following description: metal storage drums.',
    'Locate all the instances that match the following description: reddish-brown rust patches on metal barrels.',
    'Locate all the instances that match the following description: bulging metal drums with visibly raised dome-shaped lids.',
)


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1e-6,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


def parse(answer,width,height):
    detections=[]
    pattern=r'<box>\s*<(\d+)>\s*<(\d+)>\s*<(\d+)>\s*<(\d+)>\s*</box>'
    for match in re.finditer(pattern,answer):
        refs=list(re.finditer(r'<ref>(.*?)</ref>',answer[:match.start()],re.S))
        label=refs[-1].group(1).strip() if refs else 'metal drum'
        lower=label.lower();class_ids=[]
        if any(s in lower for s in ('rust','corrod','corrosion')):class_ids.append(1)
        if any(s in lower for s in ('bulg','swoll','bloat')):class_ids.append(2)
        if not class_ids:class_ids=[0]
        values=list(map(int,match.groups()))
        if any(v>1000 for v in values):continue
        x0,y0,x1,y1=values;box=[x0*width/1000,y0*height/1000,x1*width/1000,y1*height/1000]
        if x1<=x0 or y1<=y0:continue
        for cid in class_ids:
            if any(d['class_id']==cid and iou(d['bbox_xyxy'],box)>.85 for d in detections):continue
            detections.append(dict(class_id=cid,class_name=('drum','corrosion','bulge')[cid],
                confidence=None,confidence_kind='not_provided',bbox_xyxy=box,phrase=label,decision_band='unscored'))
    bodies=[d['bbox_xyxy'] for d in detections if d['class_id']==0]
    barrels=[]
    for index,box in enumerate(bodies):
        def attached(d):
            b=d['bbox_xyxy'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
            return iou(b,box)>.25 or (box[0]<=cx<=box[2] and box[1]<=cy<=box[3] and
                (b[2]-b[0])*(b[3]-b[1])<=(box[2]-box[0])*(box[3]-box[1]))
        flags={name:any(d['class_name']==name and attached(d) for d in detections)
               for name in ('corrosion','bulge')}
        barrels.append(dict(frame_id=f'proposal_{index}',bbox_xyxy=box,confidence=None,
            confidence_kind='not_provided',corrosion_observed=flags['corrosion'],bulge_observed=flags['bulge'],
            condition='rust_and_bulge' if all(flags.values()) else 'rust' if flags['corrosion'] else
                      'bulge' if flags['bulge'] else 'no_fault_located'))
    return detections,barrels
