"""Promote the reviewed painted LLW design into the fixed hall.

The 500 L stainless ILW geometry/materials stay category-specific. No pressure
mechanics or measured rust coverage are inferred from these visual fixtures.
"""
from functools import lru_cache
import math

VERSION='reviewed_llw_v2'
BODY_SWELLING=.08
LID_RISE_M=.070


def shape_spec(entry):
    from profiles import drum_profile
    from corrosion_preview import swollen_profile
    bulged='bulge' in entry.get('faults',[])
    if bulged and entry['category']!='LLW':
        raise NotImplementedError('The reviewed bulge fixture is for 208 L painted LLW drums')
    structure=entry.get('simulation_properties',{}).get('structure',{})
    swelling=float(structure.get('radial_swelling_fraction') or BODY_SWELLING) if bulged else 0.
    lid_rise=float(structure.get('lid_rise_m') or LID_RISE_M) if bulged else 0.
    profile=swollen_profile(swelling) if bulged else drum_profile(entry['category'])
    return dict(profile=profile,bulged=bulged,max_radius=max(r for r,z in profile),
                lid_rise=lid_rise,radial_fraction=swelling)


@lru_cache(maxsize=3)
def paint_maps(name):
    from corrosion_preview import weathered_maps
    from drum_textures import PAINTS
    rgb=(170,153,66) if name=='faded_yellow' else PAINTS[name]
    return weathered_maps(74,paint_rgb=rgb,prefix=f'hall_v2_{name}_s74')[0]


@lru_cache(maxsize=32)
def oxide_maps(seed):
    from corrosion_preview import weathered_maps
    _,maps,alpha=weathered_maps(seed)
    return maps,alpha


def apply_reviewed_appearance(stage,entry,materials,seed=74):
    """Apply to a freshly created drum; keep rust outside the drum label hierarchy."""
    from pxr import Gf,UsdGeom,UsdPhysics,UsdShade
    from geometry import mesh
    from materials import material
    from profiles import make_drum_mesh
    spec=shape_spec(entry)
    entry['appearance_version']=VERSION if entry['category']=='LLW' else 'stainless_ilw_v1'
    entry['shape']={'max_radius':spec['max_radius'],'lid_rise':spec['lid_rise'],'dents':[],
                    'radial_swelling_fraction':spec['radial_fraction']}
    if entry['category']!='LLW':
        return
    paint=material(stage,'HallWeathered_'+entry['paint_color'],(1,1,1),.5,textures=paint_maps(entry['paint_color']))
    root=entry['prim_path']
    if spec['bulged']:
        stage.RemovePrim(root+'/Body')
        data=make_drum_mesh(spec['profile'])
        body=mesh(stage,root+'/Body',data['points'],data['faces'],data['uv'],paint)
        body.CreateNormalsAttr(data['normals']);body.SetNormalsInterpolation('faceVarying')
        UsdPhysics.CollisionAPI.Apply(body.GetPrim())
        from corrosion_preview import dome_lid
        dome_lid(stage,entry,paint,rise=spec['lid_rise'])
        for part in ('BungLarge','BungSmall'):
            transform=UsdGeom.Xformable(stage.GetPrimAtPath(root+'/'+part)).GetOrderedXformOps()[0]
            xyz=transform.Get();r=math.hypot(xyz[0],xyz[1])
            xyz[2]+=spec['lid_rise']*(1-(r/.278)**2)**1.5
            transform.Set(xyz)
        from drums import create_plate
        stage.RemovePrim(root+'/Plate');create_plate(stage,entry,spec['profile'])
    else:
        for part in ('Body','Lid'):
            UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath(root+'/'+part)).Bind(paint)
    if 'corrosion' in entry.get('faults',[]):
        from corrosion_preview import build_oxide
        textures,alpha=oxide_maps(int(seed))
        path='/World/Defects/'+entry['id']
        oxide=build_oxide(stage,{**entry,'prim_path':path},textures,alpha,spec['profile'],
                          material_name='HallThinOxide_'+entry['id'])
        # Other release meshes use world-space coordinates under this identity
        # parent. Transform only the oxide mesh, not its siblings.
        xform=UsdGeom.Xformable(oxide)
        xform.GetOrderedXformOps()[0].Set(Gf.Vec3d(entry['x'],entry['y'],0))
        from drums import ROWS
        face=next(sign for row,_,_,sign in ROWS if row==entry['row'])
        # Keep the dense failure region on the aisle-facing side, as in the
        # reviewed fixture. Body yaw and the warning plate remain unchanged.
        xform.AddRotateZOp().Set(0. if face<0 else 180.)
        entry['defects'].append(dict(type='corrosion',subtype='thin_chipped_oxide',
            prim_path=str(oxide.GetPath()),seed=int(seed),surface_offset_m=.00035,
            appearance_version=VERSION))


def create_reviewed_drum(stage,entry,materials,seed=74):
    from drums import create_drum
    create_drum(stage,entry,materials)
    apply_reviewed_appearance(stage,entry,materials,seed)
