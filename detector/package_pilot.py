"""Assemble checked pilot frames into matching YOLO filenames, without a fake split."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from PIL import Image


def package(root):
    started=time.perf_counter()
    root=Path(root)
    target=root/'dataset'
    for name in ('images','labels','metadata'):(target/name).mkdir(parents=True,exist_ok=True)
    frames=sorted(root.glob('seed_*/frame_*/metadata.json'))
    assert len(frames)==40, len(frames)
    counts={0:0,1:0,2:0};files=[]
    for path in frames:
        source=path.parent
        name=source.parent.name+'_'+source.name
        for src,dst in ((source/'image.jpg',target/'images'/f'{name}.jpg'),
                        (source/'labels.txt',target/'labels'/f'{name}.txt'),
                        (path,target/'metadata'/f'{name}.json')):
            shutil.copy2(src,dst)
        with Image.open(target/'images'/f'{name}.jpg') as image:assert image.size==(640,640)
        for line in (target/'labels'/f'{name}.txt').read_text().splitlines():
            cls,*values=line.split();cls=int(cls);assert cls in counts
            values=list(map(float,values));assert len(values)==4 and all(0<=x<=1 for x in values)
            assert values[2]>0 and values[3]>0
            counts[cls]+=1
        files.append(dict(name=name,sha256=hashlib.sha256((target/'images'/f'{name}.jpg').read_bytes()).hexdigest()))
    manifest=dict(images=40,classes=['drum','corrosion','bulge'],class_counts=counts,files=files,
                  split=None,purpose='pilot curation, not an independent evaluation set',
                  storage='detector-data:/pilots/'+root.name,
                  source_hashes={p:hashlib.sha256((Path(__file__).resolve().parents[1]/p).read_bytes()).hexdigest()
                                 for p in ('detector/pilot_specs.py','sim/detector_studio/pilot.py')})
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2))
    manifest['package_seconds']=time.perf_counter()-started
    print(json.dumps(manifest,indent=2))
    return target


if __name__=='__main__':package(sys.argv[1])
