"""Group visible neighbouring rust chips into bounded patches, per drum only."""
import math


def merge_rust_boxes(boxes, drum_boxes):
    result=[b for b in boxes if b['class_name']!='corrosion']
    ids=sorted({b['internal_id'] for b in boxes if b['class_name']=='corrosion'})
    for internal_id in ids:
        parts=[dict(b,source_cluster_count=1) for b in boxes
               if b['class_name']=='corrosion' and b['internal_id']==internal_id]
        reference=drum_boxes.get(internal_id)
        # Never associate a rust patch with another drum or with hidden truth.
        if reference is None:
            result.extend(parts)
            continue
        x0,y0,x1,y1=reference
        width,height=x1-x0,y1-y0
        gap=max(2.,min(10.,width*.045))
        max_width,max_height=max(6.,width*.55),max(6.,height*.27)
        clusters=[]
        for part in sorted(parts,key=lambda b:(b['xyxy'][1],b['xyxy'][0],b['xyxy'][3],b['xyxy'][2])):
            best=None
            ax0,ay0,ax1,ay1=part['xyxy']
            for index,cluster in enumerate(clusters):
                bx0,by0,bx1,by1=cluster['xyxy']
                dx=max(ax0-bx1,bx0-ax1,0);dy=max(ay0-by1,by0-ay1,0)
                if math.hypot(dx,dy)>gap:continue
                union=[min(ax0,bx0),min(ay0,by0),max(ax1,bx1),max(ay1,by1)]
                uw,uh=union[2]-union[0],union[3]-union[1]
                area=uw*uh; summed=(ax1-ax0)*(ay1-ay0)+(bx1-bx0)*(by1-by0)
                if uw>max_width or uh>max_height or area>summed*2.5:continue
                score=(area,index)
                if best is None or score<best[0]:best=(score,union,index)
            if best is None:clusters.append(part)
            else:
                _,union,index=best
                clusters[index]['xyxy']=union
                clusters[index]['source_cluster_count']+=part['source_cluster_count']
        result.extend(clusters)
    return result
