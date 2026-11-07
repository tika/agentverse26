"""Isolated v2 appearance study: thin, chipped corrosion rather than raised rust strips.

Not yet applied to the full hall or its training dataset. All textures are
procedural and the rust remains separate, masked conforming geometry.
"""
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from textures import ASSETS,noise,maps
from profiles import drum_profile,radius_at


def weathered_maps(seed=74):
    ASSETS.mkdir(parents=True,exist_ok=True)
    prefix=f'preview_weathered_yellow_s{seed}_v2'
    rng=np.random.default_rng(seed)
    n=1024; yy,xx=np.mgrid[:n,:n]
    z=1-yy/(n-1)
    broad=noise(rng,n); fine=rng.random((n,n))
    paint=np.array((170,153,66))[None,None,:]+(broad[:,:,None]-.5)*22
    # Grey handling wear and vertical grime; no orange is baked into the paint.
    columns=rng.normal(0,1,(1,n))
    dirt=np.clip((broad-.35)*.18,0,.12)+np.exp(-z/.09)*.15
    paint*=1-dirt[:,:,None]
    scratch=Image.new('L',(n,n),0); draw=ImageDraw.Draw(scratch)
    for _ in range(180):
        x,y=map(int,rng.integers(n,size=2))
        draw.line((x,y,x+int(rng.integers(2,15)),y+int(rng.integers(-2,3))),fill=int(rng.integers(30,120)),width=1)
    wear=np.asarray(scratch,dtype=float)/255
    paint=paint*(1-wear[:,:,None])+np.array((100,102,91))*wear[:,:,None]
    body=maps(prefix,paint,np.clip(.48+(broad-.5)*.12,.35,.65),broad*.018+fine*.002)
    # Full cylindrical rust field, weighted to edges where water can sit.
    mask=Image.new('L',(n,n),0); draw=ImageDraw.Draw(mask)
    hoop_rows=[int((1-v)*n) for v in (1/3,2/3)]
    for _ in range(2400):
        x=int(rng.integers(n)); choice=rng.random()
        if choice<.43:y=int(np.clip(n-1-rng.exponential(38),0,n-1))
        elif choice<.62:y=int(np.clip(rng.exponential(15),0,n-1))
        elif choice<.88:y=int(np.clip(rng.choice(hoop_rows)+rng.normal(0,5),0,n-1))
        else:y=int(rng.integers(n))
        radius=int(rng.choice([1,2,3,4,7,12],p=[.23,.26,.22,.15,.10,.04]))
        draw.ellipse((x-radius,y-radius*.65,x+radius,y+radius*.65),fill=int(rng.integers(110,255)))
    # Localised coating failure on the camera-facing lower quadrant, not a uniform band.
    for cx,cy,spread,count in [(770,914,56,350),(690,892,32,130),(840,350,28,110)]:
        for _ in range(count):
            x,y=rng.normal((cx,cy),(spread,spread*.52))
            r=int(rng.integers(2,10))
            draw.ellipse((x-r,y-r*.6,x+r,y+r*.6),fill=int(rng.integers(160,255)))
    # Sparse, hairline downward wash below hoop/rim damage.
    for _ in range(36):
        x=int(rng.integers(n)); y=int(rng.choice(hoop_rows+[20]))
        length=int(rng.integers(20,140))
        draw.line((x,y,x+int(rng.integers(-3,4)),min(n-1,y+length)),fill=int(rng.integers(60,130)),width=int(rng.integers(1,3)))
    raw=np.asarray(mask,dtype=float)/255
    halo=np.asarray(mask.filter(ImageFilter.GaussianBlur(2.2)),dtype=float)/255
    alpha=np.clip(raw+.32*halo,0,1)
    # Oxide is predominantly dark red-brown; orange is restricted to fresh edges.
    mineral=np.clip((broad-.25)*2.4,0,1)
    dark=np.array((58,38,25)); red=np.array((116,65,34)); orange=np.array((155,91,42))
    rust=dark+(red-dark)*mineral[:,:,None]
    edge=np.clip((halo-raw)*4,0,1)
    rust=rust*(1-edge[:,:,None])+orange*edge[:,:,None]
    rust+=(fine[:,:,None]-.5)*12
    rust_paths=maps(prefix+'_oxide',rust,np.clip(.87+broad*.1,.85,.98),broad*.035+fine*.012)
    opacity=ASSETS/(prefix+'_oxide_opacity.png')
    Image.fromarray(np.uint8(alpha*255)).save(opacity)
    rust_paths['opacity']=opacity
    return body,rust_paths,alpha


def swollen_profile(fraction=.08):
    original=drum_profile('LLW'); h=.88
    dense=[]
    for (r0,z0),(r1,z1) in zip(original,original[1:]):
        count=max(1,math.ceil(abs(z1-z0)/.015))
        for k in range(count):
            t=k/count; z=z0+(z1-z0)*t; r=r0+(r1-r0)*t
            r*=1+fraction*math.sin(math.pi*z/h)**2
            dense.append((r,z))
    dense.append(original[-1])
    return dense


def build_oxide(stage,entry,textures,alpha,profile):
    from geometry import mesh
    from materials import material
    from pxr import UsdShade,Sdf
    # Geometry follows only occupied cells; disconnected chips share a material.
    columns,rows=256,144
    points=[];faces=[];uv=[]
    for j in range(rows):
        z0,z1=j*.88/rows,(j+1)*.88/rows
        y0=int((1-z1/.88)*1023);y1=max(y0+1,int((1-z0/.88)*1023))
        for i in range(columns):
            x0,x1=int(i*1024/columns),int((i+1)*1024/columns)
            if alpha[y0:y1,x0:x1].max()<.17:continue
            k=len(points)
            for u,z in ((i/columns,z0),((i+1)/columns,z0),((i+1)/columns,z1),(i/columns,z1)):
                a=u*2*math.pi
                # 0.35 mm overlay, versus the old 3 mm raised patches.
                r=radius_at(profile,z)+.00035
                points.append((r*math.cos(a),r*math.sin(a),z))
                uv.append((u,z/.88))
            faces.append((k,k+1,k+2,k+3))
    paint=material(stage,'PreviewThinOxide',(1,1,1),.9,textures=textures)
    # Cutout on microchips, not a solid, opaque brown feature silhouette.
    shader=UsdShade.Shader(stage.GetPrimAtPath(str(paint.GetPath())+'/Surface'))
    shader.CreateInput('opacityThreshold',Sdf.ValueTypeNames.Float).Set(.17)
    return mesh(stage,entry['prim_path']+'/SurfaceCorrosion',points,faces,uv,paint)


def dome_lid(stage,entry,paint,rise=.070):
    from geometry import mesh
    rings,segments=14,96
    points=[];faces=[];uv=[]
    radius=.278; edge=.865
    for row in range(rings+1):
        r=radius*row/rings
        z=edge+rise*(1-(r/radius)**2)**1.5
        for i in range(segments):
            a=i*2*math.pi/segments
            points.append((r*math.cos(a),r*math.sin(a),z))
    for row in range(rings):
        for i in range(segments):
            k=(i+1)%segments
            ids=(row*segments+i,(row+1)*segments+i,(row+1)*segments+k,row*segments+k)
            faces.append(ids)
            uv.extend((.5+points[idx][0]/(2*radius),.5+points[idx][1]/(2*radius)) for idx in ids)
    stage.RemovePrim(entry['prim_path']+'/Lid')
    mesh(stage,entry['prim_path']+'/Lid',points,faces,uv,paint)
