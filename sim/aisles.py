"""The team's fixed aisle geometry and deterministic navigation graph."""
import json
from pathlib import Path


def write_aisles(path=None):
    aisles = [{'id':i,'rect':[0,y-1,20,y+1],'center_y':y} for i,y in enumerate((2,6,10),1)]
    crosses = [{'id':name,'rect':[lo,0,hi,12],'center_x':center}
               for name,lo,hi,center in (('front',0,2.5,1.25),('middle',9,11,10),('back',17.5,20,18.75))]
    xs = sorted(set([round(i*1.5,2) for i in range(14)] + [1.25,10.0,18.75,20.0]))
    nodes = [{'id':f'A{aisle}_X{x:g}','x':x,'y':y,'aisle':aisle}
             for aisle,y in enumerate((2.0,6.0,10.0),1) for x in xs]
    edges = []
    for aisle in (1,2,3):
        for a,b in zip(xs,xs[1:]): edges.append([f'A{aisle}_X{a:g}',f'A{aisle}_X{b:g}'])
    for x in (1.25,10.0,18.75):
        for aisle in (1,2): edges.append([f'A{aisle}_X{x:g}',f'A{aisle+1}_X{x:g}'])
    data = {'units':'metres','up_axis':'Z','hall':[20,12,6], 'robot_start':[1.0,6.0,0.0],
            'aisles':aisles,'cross_aisles':crosses,'nodes':nodes,'edges':edges,'blocked':[]}
    target = Path(path) if path else Path(__file__).with_name('aisles.json')
    target.write_text(json.dumps(data,indent=2)+'\n')
    return data
