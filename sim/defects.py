"""Seeded, replaceable external corrosion and release evidence; no hidden visuals."""
import math
import numpy as np
from defect_geometry import surface_mesh, floor_mesh


def corrosion_specs(entry,seed,severity):
    rng=np.random.default_rng(seed)
    # Dense stage-2 inventory uses row IDs like A-L / B-R and stores the actual
    # aisle-facing normal explicitly. Fall back for the original A/B/C layout.
    face=float(entry.get('face_sign',(-1 if entry['row'] in ('A','C') else 1)))*math.pi/2
    features=[]
    for _ in range(int(rng.integers(1,4))):
        angle=face+float(rng.uniform(-.65,.65))
        if entry['category']=='LLW':
            location=rng.choice(['bottom','top','hoop','scrape'],p=[.45,.20,.20,.15])
            stage=int(rng.choice([1,2] if severity==1 else [2,3] if severity==2 else [3,4],p=[.75,.25] if severity!=3 else [.9,.1]))
            if stage==4: location='bottom'
            width=float(rng.uniform(.20,.50)); height=float(rng.uniform(.06,.15))
            if location=='bottom': z=height/2+.003
            elif location=='top': z=entry['height']-height/2-.003
            elif location=='hoop': z=entry['height']*float(rng.choice([1/3,2/3]))
            else: z=entry['height']*float(rng.uniform(.43,.67)); height=.065
            subtype=f'stage{stage}'
        else:
            subtype=str(rng.choice(['tea_stain','pitting','crevice'],p=[.4,.35,.25]))
            location='weld' if rng.random()<.7 else 'bottom'
            if subtype=='tea_stain':
                width=float(rng.uniform(.15,.40))*(.7+.1*severity); height=width*.65
                z=entry['height']*float(rng.uniform(.67,.85))
            else:
                width=float(rng.uniform(.10,.25))*(.7+.1*severity); height=float(rng.uniform(.06,.15))
                z=entry['height']-height/2-.025 if location=='weld' else height/2+.012
        feature={'type':'corrosion','subtype':subtype,'location':location,'z':float(z),'angle':angle,
                 'size':[max(.06,width),max(.06,height)],'variant':int(rng.integers(2)),
                 'mesh_seed':int(rng.integers(2**31)),'severity':severity}
        features.append(feature)
        if entry['category']=='LLW' and location in ('top','hoop'):
            length=min(float(rng.uniform(.10,.40)),z-.015)
            if length>.06:
                features.append({**feature,'subtype':'runoff','z':z-length/2,'size':[.06,length],
                                 'mesh_seed':int(rng.integers(2**31))})
        if subtype=='stage4':
            features.append({**feature,'subtype':'rust_flakes','size':[.12,.08],
                             'mesh_seed':int(rng.integers(2**31))})
    return features


def build_corrosion(stage,entry,seed,severity,specifications=None):
    from geometry import mesh
    from materials import material
    from fault_textures import fault_bank
    bank=fault_bank(entry['scene_seed'])
    result=[]
    for index,spec in enumerate(specifications if specifications is not None else corrosion_specs(entry,seed,severity)):
        path=f"/World/Defects/{entry['id']}/Corrosion_{index}"
        subtype=spec['subtype']
        texture_kind='stage2' if subtype=='runoff' else 'stage4' if subtype=='rust_flakes' else subtype
        textures=bank[f"{texture_kind}_{spec['variant']}"]
        paint=material(stage,f"Fault_{entry['id']}_{index}",(1,1,1),.9,
                       .65 if entry['category']=='ILW' else 0,textures=textures)
        if subtype=='rust_flakes':
            direction=spec['angle']; distance=entry['radius']+.04
            centre=(entry['x']+distance*math.cos(direction),entry['y']+distance*math.sin(direction))
            data=floor_mesh(np.random.default_rng(spec['mesh_seed']),centre,*spec['size'],z=.003)
        else:
            data=surface_mesh(entry,spec)
        mesh(stage,path,*data,paint)
        result.append({**spec,'prim_path':path})
    return result


def build_release(stage,entry,fault,seed):
    from geometry import mesh
    from materials import material
    from fault_textures import release_maps
    rng=np.random.default_rng(seed)
    wet=fault=='leak'
    kind='wet' if wet else 'residue'
    textures=release_maps(entry['category'],wet,entry['scene_seed'])
    paint=material(stage,f"Release_{entry['id']}_{fault}",(1,1,1),.09 if wet else .9,textures=textures)
    face=float(entry.get('face_sign',(-1 if entry['row'] in ('A','C') else 1)))*math.pi/2
    angle=face+float(rng.uniform(-.25,.25))
    length=float(rng.uniform(.45,.8)); width=length/float(rng.uniform(1.6,2.3))
    # Long axis points away from the drum; rear edge just overlaps the base.
    distance=entry['radius']+length/2-.035
    centre=(entry['x']+distance*math.cos(angle),entry['y']+distance*math.sin(angle))
    path=f"/World/Defects/{entry['id']}/Spill_{0 if wet else 2}"
    mesh(stage,path,*floor_mesh(rng,centre,width,length,yaw=angle-math.pi/2),paint)
    result=[{'type':'spill','subtype':'wet_puddle' if wet else 'dried_residue','prim_path':path,
             'centre_xy':list(centre),'size':[width,length],'z':.002,'angle':angle}]
    if wet:
        length=entry['height']-.06
        spec={'angle':angle,'z':entry['height']/2,'size':[.065,length], 'mesh_seed':int(rng.integers(2**31))}
        path=f"/World/Defects/{entry['id']}/Spill_1"
        mesh(stage,path,*surface_mesh(entry,spec),paint)
        result.append({'type':'spill','subtype':'wet_trail','prim_path':path,**spec})
    if not wet or entry['category']=='LLW':
        height=.075 if not wet else .035
        spec={'angle':angle,'z':entry['height']-.09 if not wet else .04,
              'size':[.14,height], 'mesh_seed':int(rng.integers(2**31))}
        path=f"/World/Defects/{entry['id']}/Spill_{3 if not wet else 4}"
        mesh(stage,path,*surface_mesh(entry,spec),paint)
        result.append({'type':'spill','subtype':'dry_deposit' if not wet else 'wet_base_band','prim_path':path,**spec})
    return result
