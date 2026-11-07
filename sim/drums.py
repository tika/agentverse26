"""Fixed 28-drum inventory, nominal meshes, aisle-facing plates and category swap."""
import json
import math
from pathlib import Path
import numpy as np
from profiles import drum_profile, make_drum_mesh, radius_at

INVENTORY=Path(__file__).with_name('drums.json')
PAINT_NAMES=('faded_yellow','mid_grey','dark_blue')
# v1.2.1 (Levi reference photo): every drum is yellow paint; linear-RGB base colours.
YELLOWS={'safety_yellow':(.78,.56,.02),'warm_yellow':(.80,.50,.02),'faded_yellow':(.66,.53,.08)}  # tuned to reference R/G≈1.33
# LLW radius .299 m = real 208 L drum (tika 19231d1; Param 598 mm); dense layout pallets widened to fit.
CATEGORIES={'LLW':(.299,.88,1),'ILW':(.40,1.20,20)}
ROWS=(('A',3.45,1,-1),('B',4.55,2,1),('C',7.45,2,-1),('D',8.55,3,1))


def nominal_entry(entry,category):
    if category not in CATEGORIES: raise ValueError('Category must be LLW or ILW')
    radius,height,strength=CATEGORIES[category]
    return {**entry,'category':category,'radius':radius,'height':height,'source_strength':strength,
            'state':'clean','faults':[],'corrosion_severity':0,'defects':[],
            'shape':{'max_radius':max(r for r,_ in drum_profile(category)),'lid_rise':0.0,'dents':[]},
            'obstructed':False,'internal_corrosion':False,
            'paint_color':PAINT_NAMES[entry['appearance_seed']%3] if category=='LLW' else None}


def make_inventory(seed=42):
    rng=np.random.default_rng(seed)
    entries=[]
    first_slot=1
    for category,xs in (('LLW',(3.0,4.5,6.0,7.5)),('ILW',(12.0,14.0,16.0))):
        for row,y,aisle,_ in ROWS:
            for slot,x in enumerate(xs, start=first_slot):
                name=f'D{len(entries)+1:02d}'
                entry={'id':name,'category':category,'zone':'A' if x<10 else 'B','row':row,
                       'display_id':f'{row}{slot:02d}',
                       'x':x,'y':y,'yaw':float(rng.uniform(0,2*math.pi)),'facing_aisle':aisle,
                       'prim_path':'/World/Drums/'+name,'scene_seed':seed,
                       'appearance_seed':int(rng.integers(2**31))}
                entries.append(nominal_entry(entry,category))
        first_slot+=len(xs)
    return entries


def write_inventory(entries):
    INVENTORY.write_text(json.dumps(entries,indent=2)+'\n')


def drum_materials(stage,seed):
    from drum_textures import clean_surfaces
    from materials import material
    result={}
    colors = {'mid_grey':(.32,.35,.36), 'dark_blue':(.07,.16,.25), 'stainless':(.48,.49,.50), **YELLOWS}
    for name,color in colors.items():
        metal = .75 if name == 'stainless' else .1
        result[name] = material(stage,'Drum_'+name,color,.45,metal)
        result[name+'_lid'] = material(stage,'Drum_'+name+'_Lid',color,.5,metal)
    result['cap']=material(stage,'DrumBungSteel',(.30,.33,.34),.4,.8)
    result['filter']=material(stage,'DrumVentFilter',(.12,.14,.14),.65,.1)
    return result


def create_plate(stage,entry,profile):
    from geometry import mesh
    from materials import material
    from drum_textures import plate_texture
    direction=entry.get('face_sign') or next(sign for row,_,_,sign in ROWS if row==entry['row'])
    angle=direction*math.pi/2-entry['yaw']
    z_center=entry['height']*(.3 if 'face_sign' in entry else .6)
    angle_width=.20/radius_at(profile,z_center)
    low,high=z_center-.07,z_center+.07
    heights=sorted(set([low+.14*i/4 for i in range(5)] + [z for _,z in profile if low<z<high]))
    points,faces,uv=[],[],[]
    for z in heights:
        radius=radius_at(profile,z)+.002
        for column in range(13):
            theta=angle-angle_width/2+angle_width*column/12
            points.append((radius*math.cos(theta),radius*math.sin(theta),z))
    for row in range(len(heights)-1):
        for column in range(12):
            index=row*13+column
            faces.append((index,index+1,index+14,index+13))
            v0,v1=(heights[row]-low)/.14,(heights[row+1]-low)/.14
            uv.extend([(column/12,v0),((column+1)/12,v0),((column+1)/12,v1),(column/12,v1)])
    paint=material(stage,'DrumPlate_'+entry['id']+'_'+entry['category'],(1,1,1),.6,textures=plate_texture(entry))
    return mesh(stage,entry['prim_path']+'/Plate',points,faces,uv,paint)


def create_stencil(stage,entry,profile):
    """Large black stencilled package ID on a curved band, facing the aisle (v1.2.1 F13)."""
    from geometry import mesh
    from materials import material
    from drum_textures import stencil_texture
    angle=entry['face_sign']*math.pi/2-entry['yaw']
    band_h=.16 if entry['category']=='LLW' else .2
    z_center=entry['height']*.72
    low=z_center-band_h/2
    angle_width=.42/radius_at(profile,z_center)
    heights=sorted(set([low+band_h*i/4 for i in range(5)] + [z for _,z in profile if low<z<low+band_h]))
    points,faces,uv=[],[],[]
    for z in heights:
        radius=radius_at(profile,z)+.0015
        for column in range(25):
            theta=angle-angle_width/2+angle_width*column/24
            points.append((radius*math.cos(theta),radius*math.sin(theta),z))
    for row in range(len(heights)-1):
        for column in range(24):
            index=row*25+column
            faces.append((index,index+1,index+26,index+25))
            v0,v1=(heights[row]-low)/band_h,(heights[row+1]-low)/band_h
            # Same convention as the plate (verified readable): u increases with theta.
            uv.extend([(column/24,v0),((column+1)/24,v0),((column+1)/24,v1),(column/24,v1)])
    paint=material(stage,'DrumStencil_'+entry['id'],(1,1,1),.5,.1,textures=stencil_texture(entry,YELLOWS[entry['paint_color']]))
    return mesh(stage,entry['prim_path']+'/Stencil',points,faces,uv,paint)


def create_drum(stage,entry,materials):
    from pxr import UsdGeom, UsdPhysics, Gf
    from geometry import mesh,cylinder
    from sensors import author_gamma_source
    path=entry['prim_path']
    if stage.GetPrimAtPath(path): stage.RemovePrim(path)
    root=UsdGeom.Xform.Define(stage,path)
    author_gamma_source(root.GetPrim(),entry)
    root.AddTranslateOp().Set(Gf.Vec3d(entry['x'],entry['y'],entry.get('base_z',0.0)))
    root.AddRotateZOp().Set(math.degrees(entry['yaw']))
    profile=drum_profile(entry['category'])
    data=make_drum_mesh(profile)
    paint=entry['paint_color'] or 'stainless'
    ilw_lid=paint+'_lid' if entry.get('face_sign') else 'stainless_lid'
    ilw_metal=paint if entry.get('face_sign') else 'stainless'
    body=mesh(stage,path+'/Body',data['points'],data['faces'],data['uv'],materials[paint])
    body.CreateNormalsAttr(data['normals'])
    body.SetNormalsInterpolation('faceVarying')
    UsdPhysics.CollisionAPI.Apply(body.GetPrim())
    height=entry['height']
    if entry['category']=='LLW':
        cylinder(stage,path+'/Lid',(0,0,height-.017),.278,.004,materials[paint+'_lid'],segments=64)
        cylinder(stage,path+'/BungLarge',(.13,.04,height-.009),.0254,.012,materials['cap'],segments=24)
        cylinder(stage,path+'/BungSmall',(-.13,-.04,height-.010),.009525,.01,materials['cap'],segments=20)
    else:
        cylinder(stage,path+'/Lid',(0,0,1.153),.360,.004,materials[ilw_lid],segments=64)
        cylinder(stage,path+'/VentHousing',(.11,.03,1.174),.035,.038,materials[ilw_metal],segments=24)
        cylinder(stage,path+'/VentCap',(.11,.03,1.197),.036,.006,materials['filter'],segments=24)
    # Every drum carries its stencil + trefoil (F13); back-row drums are hidden by occlusion,
    # not by missing markings. Location plates only on aisle-facing drums.
    if entry.get('face_sign'):
        create_stencil(stage,entry,profile)
    if entry.get('visible_face',True):
        create_plate(stage,entry,profile)


def build_drums(seed=42):
    from isaacsim.core.experimental.utils.stage import get_current_stage
    from pxr import UsdGeom
    stage=get_current_stage()
    if stage.GetPrimAtPath('/World/Drums'): stage.RemovePrim('/World/Drums')
    UsdGeom.Xform.Define(stage,'/World/Drums')
    from stacking import stack_inventory, load_config, pallets
    config=load_config()
    entries=stack_inventory(make_inventory(seed),config)
    materials=drum_materials(stage,seed)
    for entry in entries: create_drum(stage,entry,materials)
    if config.get('enabled',True): build_pallets(stage,entries,config)
    write_inventory(entries)
    return entries


def build_pallets(stage,entries,config):
    """Dark plastic pallets (v1.2.1): deck plus three runners under every stack tier."""
    from pxr import UsdGeom
    from geometry import box
    from materials import material
    from stacking import pallets
    root='/World/Pallets'
    if stage.GetPrimAtPath(root): stage.RemovePrim(root)
    UsdGeom.Xform.Define(stage,root)
    steel=material(stage,'PalletDarkPlastic',(.045,.048,.052),.72,0.0)
    for stack_id,tier,(x,y,z0),p in pallets(entries,config):
        name=f"{root}/P_{stack_id.replace('-','_')}_T{tier}"
        s,deck,run=p['size_m'],p['deck_m'],p['runner_m']
        box(stage,name+'_Deck',(x,y,z0+run+deck/2),(s,s,deck),steel,collision=True)
        for i,dy in enumerate((-s/2+.05,0,s/2-.05)):
            box(stage,f'{name}_Runner{i}',(x,y+dy,z0+run/2),(s,.1,run),steel,collision=True)


def set_drum_category(drum_id,category):
    from isaacsim.core.experimental.utils.stage import get_current_stage
    entries=json.loads(INVENTORY.read_text())
    index=next((i for i,entry in enumerate(entries) if entry['id']==drum_id),None)
    if index is None: raise KeyError(drum_id)
    entry=nominal_entry(entries[index],category)
    stage=get_current_stage()
    was_labelled=any('LabelsAPI:' in schema for schema in stage.GetPrimAtPath(entry['prim_path']).GetAppliedSchemas())
    defect_path='/World/Defects/'+drum_id
    if stage.GetPrimAtPath(defect_path): stage.RemovePrim(defect_path)
    create_drum(stage,entry,drum_materials(stage,entry['scene_seed']))
    entries[index]=entry
    write_inventory(entries)
    # Category changes reset faults to clean and keep the new root labelled.
    if was_labelled:
        from labels import label_drum
        label_drum(stage,entry)
    return entry


def set_drum_faults(drum_id,faults,seed=42,severity=2):
    """Replace this drum's Step 3/4 fault meshes; unsupported later faults fail explicitly."""
    from isaacsim.core.experimental.utils.stage import get_current_stage
    from defects import build_corrosion, build_release
    supported={'corrosion','leak','residue'}
    if set(faults)-supported:
        raise NotImplementedError('Currently supported: corrosion, leak, residue')
    if severity not in (1,2,3): raise ValueError('Severity must be 1, 2 or 3')
    entries=json.loads(INVENTORY.read_text())
    entry=next((e for e in entries if e['id']==drum_id),None)
    if entry is None: raise KeyError(drum_id)
    stage=get_current_stage()
    path='/World/Defects/'+drum_id
    if stage.GetPrimAtPath(path): stage.RemovePrim(path)
    entry['faults']=sorted(set(faults))
    entry['state']='+'.join(entry['faults']) or 'clean'
    entry['corrosion_severity']=severity if 'corrosion' in faults else 0
    entry['defects']=[]
    if 'corrosion' in faults: entry['defects']+=build_corrosion(stage,entry,seed,severity)
    for index,fault in enumerate(('leak','residue')):
        if fault in faults: entry['defects']+=build_release(stage,entry,fault,seed+1009*(index+1))
    write_inventory(entries)
    # Dataset labels are always restored after a state change.
    from labels import label_drum
    label_drum(stage,entry)
    return entry


def set_drum_state(drum_id,state,seed=42,severity=2):
    """Teammate compatibility helper: clean/rusted/rust/spill or composable fault list."""
    aliases={'rust':'corrosion','rusted':'corrosion','spill':'leak','ok':'clean'}
    if isinstance(state,str):
        state=aliases.get(state,state)
        faults=[] if state=='clean' else [aliases.get(s,s) for s in state.split('+')]
    else: faults=list(state)
    return set_drum_faults(drum_id,faults,seed,severity)
