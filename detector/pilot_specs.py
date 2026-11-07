"""Seeded pilot assignments. Printed identity and faults use independent RNG streams."""
import math
import numpy as np

CLASSES = ['drum', 'corrosion', 'bulge']


def clear_inspection_ray(eye,target,entries,target_id):
    """Conservative camera-to-target centre ray, using a 0.36m clearance radius."""
    dx,dy=target[0]-eye[0],target[1]-eye[1]
    length2=dx*dx+dy*dy
    for entry in entries:
        if entry['id']==target_id:continue
        if math.hypot(entry['x']-eye[0],entry['y']-eye[1])<.36:return False
        t=((entry['x']-eye[0])*dx+(entry['y']-eye[1])*dy)/length2
        if 0<=t<=1:
            distance=math.hypot(entry['x']-(eye[0]+t*dx),entry['y']-(eye[1]+t*dy))
            if distance<.36:return False
    return True


def scene_spec(seed,count=4):
    shape_rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    id_rng = np.random.default_rng(np.random.SeedSequence([seed, 2]))
    appearance_rng = np.random.default_rng(np.random.SeedSequence([seed, 3]))
    conditions = [(False, False), (True, False), (False, True), (True, True)]
    if not 4<=count<=8:raise ValueError('Use 4–8 drums')
    choices=[(False,False),(True,False),(False,True),(True,True)]
    conditions += [choices[int(shape_rng.choice(4,p=[.30,.30,.25,.15]))] for _ in range(count-4)]
    shape_rng.shuffle(conditions)
    ids = id_rng.choice([f'{r}{i:02d}' for r in 'ABCD' for i in range(1, 8)], count, replace=False)
    entries = []
    for i, ((rust, bulge), display_id) in enumerate(zip(conditions, ids)):
        entries.append(dict(id=f'D{i+1:02d}', display_id=str(display_id), rust=rust, bulge=bulge,
                            x=(i-1.5)*1.1, y=float(shape_rng.uniform(-.12, .12)),
                            yaw=float(shape_rng.uniform(-math.pi, math.pi)),
                            radial_fraction=float(shape_rng.uniform(.07,.09)) if bulge else 0.,
                            lid_rise_m=float(shape_rng.uniform(.065,.075)) if bulge else 0.,
                            rust_seed=int(appearance_rng.integers(100000, 2000000000))))
    return entries


def diversity_spec(seed, frame_count=5):
    """Independent streams; three close inspection + two context views per five.

    All 4/6/8 drums remain visible in USD throughout capture. Close views can
    include neighbours; every actually visible drum gets an annotation.
    """
    count=int(np.random.default_rng(np.random.SeedSequence([seed,7])).choice([4,6,8]))
    entries = scene_spec(seed,count)
    layout_rng = np.random.default_rng(np.random.SeedSequence([seed, 4]))
    env_rng = np.random.default_rng(np.random.SeedSequence([seed, 5]))
    view_rng = np.random.default_rng(np.random.SeedSequence([seed, 6]))
    layout = str(layout_rng.choice(['row', 'staggered', 'cluster']))
    coords = {'row': [(-1.2,0),(-.4,0),(.4,0),(1.2,0)],
              'staggered': [(-.95,-.6),(.6,-.6),(-.6,.6),(.95,.6)],
              'cluster': [(-.65,-.65),(.65,-.65),(-.65,.65),(.65,.65)]}[layout]
    if count>4:
        columns=(count+1)//2
        coords=[((i%columns-(columns-1)/2)*1.0 + (.15*(i//columns) if layout=='staggered' else 0),
                 (i//columns-.5)*1.3) for i in range(count)]
    rotation = float(layout_rng.uniform(-math.pi, math.pi))
    for entry, (x,y) in zip(entries, coords):
        x += float(layout_rng.uniform(-.05,.05)); y += float(layout_rng.uniform(-.05,.05))
        entry['x'] = x*math.cos(rotation)-y*math.sin(rotation)
        entry['y'] = x*math.sin(rotation)+y*math.cos(rotation)
    palettes = [((.28,.30,.29),(.44,.45,.42)), ((.22,.24,.26),(.32,.37,.40)),
                ((.38,.34,.28),(.51,.47,.39)), ((.35,.36,.35),(.57,.58,.56))]
    floor,wall = palettes[int(env_rng.integers(len(palettes)))]
    light_rotation = float(env_rng.uniform(-math.pi,math.pi))
    lights=[]
    for name, radius,z,power in [('Key',3.,3.1,1900),('Fill',3.8,2.5,950),('Top',1.7,3.5,1300)]:
        angle=light_rotation+len(lights)*2*math.pi/3
        lights.append(dict(name=name,position=[radius*math.cos(angle),radius*math.sin(angle),z],
                           power=float(power*env_rng.uniform(.65,1.4)),
                           temperature_k=float(env_rng.uniform(3900,6900)),
                           size_m=float(env_rng.uniform(1.5,3.5))))
    environment=dict(layout=layout,floor_color=floor,wall_color=wall,
                     floor_roughness=float(env_rng.uniform(.55,.95)),
                     ambient_power=float(env_rng.uniform(100,200)),lights=lights)
    if frame_count<1:raise ValueError('frame_count must be positive')
    selected=list(map(int,view_rng.permutation(count)))
    # Rotate through front/right/back/left across seeds, independently of faults.
    frames=[]
    for i in range(frame_count):
        single=i%5<3
        target_entry=entries[selected[((i//5)*3+i%5)%count]] if single else None
        focus=(target_entry['x'],target_entry['y']) if single else (0.,0.)
        bearing=-math.pi/2+((seed+i)%4)*math.pi/2+float(view_rng.uniform(-.30,.30))
        distance=float(view_rng.uniform(1.0,1.5) if single else view_rng.uniform(2.8,3.7))
        height=float(view_rng.uniform(.45,.8))
        target_z=float(view_rng.uniform(.43,.51))
        eye=[focus[0]+distance*math.cos(bearing),focus[1]+distance*math.sin(bearing),height]
        target=[focus[0],focus[1],target_z]
        if single:
            for attempt in range(12):
                if clear_inspection_ray(eye,target,entries,target_entry['id']):break
                bearing+=math.pi/6
                eye=[focus[0]+distance*math.cos(bearing),focus[1]+distance*math.sin(bearing),height]
            else:raise ValueError('No clear inspection viewpoint for seeded target')
        frames.append(dict(mode='inspection' if single else 'context',target_id=target_entry['id'] if single else None,
                           bearing_rad=bearing,distance_m=distance,eye=eye,target=target,
                           light_scale=float(view_rng.uniform(.8,1.2))))
    # Background clutter is independent of target conditions; one context view
    # gets a low foreground crate, with every remaining visible drum labelled.
    environment['clutter']=[dict(position=[float(env_rng.choice([-1,1])*env_rng.uniform(2.2,3.2)),
                                          float(env_rng.uniform(-2,2)),.22],
                                 size=[float(env_rng.uniform(.35,.7)),float(env_rng.uniform(.35,.7)),.44])
                              for _ in range(int(env_rng.integers(1,4)))]
    return dict(version='diversity_v3_persistent',seed=seed,entries=entries,environment=environment,frames=frames)
