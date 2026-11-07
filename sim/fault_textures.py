"""Small cached procedural rust/stainless/release bank, all maps <=512 px."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from textures import ASSETS, noise, maps


def fault_bank(seed=42):
    ASSETS.mkdir(parents=True,exist_ok=True)
    result = {}
    names = [f'stage{s}_{v}' for s in range(1,5) for v in range(2)]
    names += [f'{kind}_{v}' for kind in ('tea_stain','pitting','crevice','wet','residue') for v in range(2)]
    for index,name in enumerate(names):
        prefix = f'fault_{name}_s{seed}_v1'
        paths = {c:ASSETS/f'{prefix}_{c}.png' for c in ('diffuseColor','roughness','normal','opacity')}
        if not all(p.exists() for p in paths.values()):
            rng = np.random.default_rng(seed+index*7919)
            n = 512
            grain, fine = noise(rng,n), rng.random((n,n))
            yy,xx = np.mgrid[:n,:n]
            u,v = xx/(n-1),1-yy/(n-1)
            border = np.minimum.reduce([u,1-u,v,1-v])
            alpha = np.clip(border/.045,0,1)
            relief = grain*.12
            rough = np.full((n,n),.94)
            if name.startswith('stage'):
                stage = int(name[5])
                # Mineral layers: magnetite, hematite, active orange, ochre bloom.
                colors = np.array([(43,26,18),(116,53,26),(193,96,36),(210,161,78)])
                bands = np.clip((grain-.22)*5,0,2.999)
                lo = bands.astype(int)
                weight = (bands-lo)[:,:,None]
                rgb = colors[lo]*(1-weight)+colors[np.minimum(lo+1,3)]*weight
                relief = grain*.7 + fine*.09
                rough = np.clip(.88+grain*.12,.88,1)
                if stage == 1:
                    # Translucent scratched oxide; underlying paint remains visible.
                    scratches = Image.new('L',(n,n),0)
                    draw = ImageDraw.Draw(scratches)
                    for _ in range(35):
                        x,y = rng.integers(0,n,2)
                        draw.line((int(x),int(y),int(x+rng.integers(20,110)),int(y+rng.integers(-5,6))),fill=255,width=int(rng.integers(1,5)))
                    mask = np.asarray(scratches,dtype=float)/255
                    halo = np.asarray(scratches.filter(ImageFilter.GaussianBlur(10)),dtype=float)/255
                    rgb = rgb*.7+np.array((143,109,65))*.3
                    alpha *= .26+.70*mask+.22*halo
                    relief = mask*.15
                    rough[:] = .65
                elif stage == 2:
                    blisters = Image.new('L',(n,n),0)
                    draw = ImageDraw.Draw(blisters)
                    for _ in range(100):
                        x,y = rng.integers(0,n,2); r=int(rng.integers(3,16))
                        draw.ellipse((int(x-r),int(y-r),int(x+r),int(y+r)),fill=int(rng.integers(100,255)))
                    blister = np.asarray(blisters,dtype=float)/255
                    rgb = rgb*(.6+.4*blister[:,:,None])+np.array((185,142,71))[None,None,:]*(1-blister[:,:,None])*.25
                    relief = blister*.85+grain*.2
                    alpha *= .65+.35*blister
                else:
                    # Angular, raised laminar scale plus dark millimetre-scale pits.
                    flakes = Image.new('L',(n,n),0); draw=ImageDraw.Draw(flakes)
                    for _ in range(160):
                        x,y = rng.integers(0,n,2); r=int(rng.integers(3,22))
                        draw.polygon([(int(x-r),int(y)),(int(x),int(y-r//2)),(int(x+r),int(y+2)),(int(x+2),int(y+r))],fill=int(rng.integers(40,255)))
                    scale=np.asarray(flakes,dtype=float)/255
                    relief += scale*.7
                    rgb *= (.65+.5*scale[:,:,None])
                    pits = fine > .991
                    rgb[pits] = (39,25,19)
                    relief[pits] -= .5
                    if stage == 4:
                        rgb *= .7
                        # Dark pseudo-perforation spots; no through-hole physics claimed.
                        holes=Image.new('L',(n,n),0); draw=ImageDraw.Draw(holes)
                        for _ in range(3):
                            x,y=rng.integers(80,n-80,2); r=int(rng.integers(4,12))
                            draw.ellipse((int(x-r),int(y-r),int(x+r),int(y+r)),fill=255)
                        mask=np.asarray(holes)>0; rgb[mask]=(13,12,10); relief[mask]-=1
            elif name.startswith('tea_stain'):
                strength=np.clip((grain-.28)*1.9,.12,.7)
                rgb=np.array((125,91,53))[None,None,:]+(grain[:,:,None]-.5)*38
                alpha *= strength
                rough[:]=.50
                relief=grain*.045
            elif name.startswith(('pitting','crevice')):
                canvas=Image.new('RGB',(n,n),(139,119,84)); draw=ImageDraw.Draw(canvas)
                pits=Image.new('L',(n,n),0); pd=ImageDraw.Draw(pits)
                if name.startswith('pitting'):
                    for _ in range(22):
                        x,y=map(int,rng.integers((50,35),(n-50,n//2)))
                        r=int(rng.integers(2,7)); length=int(rng.integers(70,260))
                        draw.line((x,y,x+int(rng.integers(-5,6)),min(n-4,y+length)),fill=(134,64,31),width=int(rng.integers(2,7)))
                        draw.ellipse((x-r,y-r,x+r,y+r),fill=(28,24,21)); pd.ellipse((x-r,y-r,x+r,y+r),fill=255)
                else:
                    points=[(x,int(n*.24+8*np.sin(x/35)+rng.normal(0,2))) for x in range(n)]
                    draw.line(points,fill=(35,28,21),width=9)
                    for k in range(3):
                        x=100+k*120
                        draw.line((x,120,x+12,180,x-3,210,x+14,260),fill=(48,33,23),width=2)
                        draw.line((x+10,175,x+40,205),fill=(48,33,23),width=1)
                rgb=np.asarray(canvas,dtype=float)
                relief=grain*.03-np.asarray(pits,dtype=float)/255*.8
                alpha *= .55+.45*grain
                rough[:]=.5
            elif name.startswith('wet'):
                rgb=np.array((64,68,65))[None,None,:]+(grain[:,:,None]-.5)*10
                rough[:]=.09
                alpha *= .66+.2*grain
                relief=grain*.01
            else:
                rgb=np.array((177,171,145))[None,None,:]+(grain[:,:,None]-.5)*30
                rough[:]=.9
                alpha *= .50+.4*grain
                relief=grain*.25
            maps(prefix,rgb,rough,relief)
            Image.fromarray(np.uint8(np.clip(alpha,0,1)*255)).save(paths['opacity'])
        result[name]=paths
    return result


def release_maps(category,wet,seed=42):
    """Category-specific wet film or dry evaporative rings, shared across drums."""
    prefix=f"release_{category}_{'wet' if wet else 'dry'}_s{seed}_v1"
    paths={c:ASSETS/f'{prefix}_{c}.png' for c in ('diffuseColor','roughness','normal','opacity')}
    if all(p.exists() for p in paths.values()): return paths
    ASSETS.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(seed+(1 if category=='ILW' else 0)+(10 if wet else 0))
    n=512; yy,xx=np.mgrid[:n,:n]
    u,v=xx/(n-1),yy/(n-1)
    grain=noise(rng,n)
    # floor_mesh is a radial fan: elliptical radius aligns rings with the mesh.
    radius=np.sqrt(((u-.5)*2)**2+((v-.5)*2)**2)
    edge=np.clip((radius-.82)/.18,0,1)
    if wet:
        base=np.array((115,104,79) if category=='LLW' else (154,158,149))
        rgb=base[None,None,:]+(grain[:,:,None]-.5)*8
        meniscus=np.exp(-((radius-.96)/.02)**2)
        rgb+=meniscus[:,:,None]*35
        rough=.04+.35*edge
        relief=grain*.015
        alpha=np.clip((1.03-radius)/.08,0,1)*.82
        if category=='ILW':
            crust=meniscus*(grain>.45)
            rgb=rgb*(1-crust[:,:,None])+np.array((223,222,207))*crust[:,:,None]
            relief+=crust*.5
    else:
        base=np.array((157,104,60) if category=='LLW' else (197,197,182))
        rgb=base[None,None,:]+(grain[:,:,None]-.5)*18
        relief=grain*.06
        for r in (.42,.64,.82,.98):
            ring=np.exp(-((radius-r)/.017)**2)
            if category=='LLW': rgb-=ring[:,:,None]*40
            else: rgb+=ring[:,:,None]*32
            relief+=ring*(.2 if category=='LLW' else .8)
        rough=np.full((n,n),.88)
        alpha=np.clip((1.03-radius)/.06,0,1)*.9
    maps(prefix,rgb,rough,relief)
    Image.fromarray(np.uint8(np.clip(alpha,0,1)*255)).save(paths['opacity'])
    return paths
