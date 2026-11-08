"""Exactly 1,500 procedural condition frames; generation seeds never cross splits."""
import hashlib
import json
from pathlib import Path
import random

CLASSES=['normal','rust','bulge','rust_and_bulge']


def make_plan(layout):
    sessions=[]
    for index in range(50):
        seed=260811000+index;rng=random.Random(seed)
        split='train' if index<40 else 'val' if index<45 else 'test'
        primary=[];conditions={}
        for cat in ('LLW','ILW'):
            for tier in (1,2):
                pool=[d for d in layout['drums'] if d['category']==cat and d['location']['tier']==tier and d['location']['depth']==1]
                chosen=rng.sample(pool,8)
                order=list(range(4))*2;rng.shuffle(order)
                for d,c in zip(chosen,order):
                    conditions[d['id']]=c
                    primary.append(dict(drum_id=d['id'],condition=c,category=cat,tier=tier))
        # Context neighbours also receive independent, balanced-in-expectation states.
        selected={d['id']:d for d in layout['drums'] if d['id'] in conditions}
        for d in layout['drums']:
            if d['id'] not in conditions and d['location']['tier']<=2 and any(abs(d['x']-p['x'])<1.35 and abs(d['y']-p['y'])<1.3 for p in selected.values()):
                conditions[d['id']]=rng.randrange(4)
        omit_tier=1+index%2
        for cat,c,tier in (('LLW',index%4,omit_tier),('ILW',(index+2)%4,3-omit_tier)):
            item=next(d for d in primary if d['category']==cat and d['condition']==c and d['tier']==tier)
            primary.remove(item)
        rng.shuffle(primary);frames=[]
        for i,d in enumerate(primary):
            angle=rng.uniform(-45,45) if i%5 else rng.choice((-1,1))*rng.uniform(45,60)
            distance=rng.uniform(1.25,1.85) if d['tier']==1 else rng.uniform(1.9,2.5)
            frames.append({**d,'name':f's{seed}_f{i:02d}','angle_deg':round(angle,3),'distance_m':round(distance,3),
                           'exposure_scale':round(rng.uniform(.95,1.35),3),'jitter_x_m':round(rng.uniform(-.12,.12),3)})
        sessions.append(dict(seed=seed,split=split,conditions=conditions,frames=frames))
    assert len(sessions)==50 and sum(len(s['frames']) for s in sessions)==1500
    return dict(schema='canis_whole_barrel_condition_v2',classes=CLASSES,resolution=[384,384],
                counts={'train':1200,'val':150,'test':150},seeds_by_split={k:[s['seed'] for s in sessions if s['split']==k] for k in ('train','val','test')},
                appearance='Exact shared warehouse rust/bulge generators; seeded new patterns, shapes and printed IDs.',sessions=sessions)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('map');p.add_argument('out');a=p.parse_args()
    plan=make_plan(json.loads(Path(a.map).read_text()));Path(a.out).write_text(json.dumps(plan,indent=2))
    print(plan['counts'])
