"""Shared clean-paint/stainless banks and one procedural ID plate per drum."""
import numpy as np
from PIL import Image, ImageDraw
from textures import ASSETS, noise, maps, text_image

PAINTS = {'faded_yellow':(169,166,89),'mid_grey':(113,125,125),'dark_blue':(38,67,91)}


def clean_surfaces(seed=42):
    ASSETS.mkdir(parents=True,exist_ok=True)
    rng = np.random.default_rng(seed)
    result = {}
    for name,color in {**PAINTS,'stainless':(162,168,170)}.items():
        local = np.random.default_rng(int(rng.integers(2**31)))
        prefix = f'drum_{name}_s{seed}_v1'
        expected = lambda key: {channel:ASSETS/f'{key}_{channel}.png'
                               for channel in ('diffuseColor','roughness','normal')}
        if not all(p.exists() for p in [*expected(prefix).values(),*expected(prefix+'_lid').values()]):
            n=1024
            grain = noise(local,n)
            yy,xx = np.mgrid[:n,:n]
            v = 1-yy/(n-1)
            rgb = np.array(color)[None,None,:]+(grain[:,:,None]-.5)*13
            if name == 'stainless':
                brushing = local.normal(0,1,(1,n))
                rough = np.clip(.35 + brushing*.025 + (grain-.5)*.04,.28,.42)
                rough = np.broadcast_to(rough,(n,n)).copy()
                # A faint weld heat-tint band is present on every clean ILW drum.
                band = np.exp(-((v-1.17/1.2)/.007)**2)*.23
                tint = np.array((170,147,104))
                rgb = rgb*(1-band[:,:,None])+tint*band[:,:,None]
                relief = np.broadcast_to(brushing*.025,(n,n)).copy()+grain*.03
            else:
                grime = np.exp(-v/.065)*.16
                rgb *= 1-grime[:,:,None]
                rough = .35+(grain-.5)*.06+grime*.3
                relief = grain*.10
                seam = int(local.integers(50,n-50))
                relief[:,seam:seam+2] += .16
                # Tiny pale cosmetic scratches: no orange and no exposed metal patches.
                image = Image.fromarray(np.uint8(np.clip(rgb,0,255)))
                draw=ImageDraw.Draw(image)
                for _ in range(45):
                    x,y=int(local.integers(n)),int(local.integers(100,n-70))
                    pale=tuple(min(255,c+int(local.integers(7,17))) for c in color)
                    draw.line((x,y,x+int(local.integers(3,14)),y+1),fill=pale,width=1)
                rgb=np.asarray(image)
            maps(prefix,rgb,rough,relief)
            dust=noise(local,512)
            lid_rgb=np.array(color)[None,None,:]+(dust[:,:,None]-.5)*18
            lid_rgb=lid_rgb*.92+np.array((162,162,150))[None,None,:]*.08
            maps(prefix+'_lid',lid_rgb,np.clip(.49+(dust-.5)*.1,.4,.6),dust*.08)
        result[name]={'body':expected(prefix),'lid':expected(prefix+'_lid')}
    return result


def plate_texture(entry):
    # Cache key includes the printed text: stage-2 plates print the location code.
    safe=entry['display_id'].replace('-','')
    path=ASSETS/f'plate_{entry["id"]}_{entry["category"]}_{safe}_v5.png'
    if path.exists(): return {'diffuseColor':path}
    ASSETS.mkdir(parents=True,exist_ok=True)
    background=(225,190,45)
    image=Image.new('RGB',(512,358),background)
    draw=ImageDraw.Draw(image)
    draw.rectangle((5,5,506,352),outline=(24,25,22),width=5)
    dense = 'face_sign' in entry  # v1.2.1: the stencil carries the drum's single trefoil (F13)
    if not dense:
        for angle in (60,180,300): draw.pieslice((29,28,143,142),angle,angle+60,fill=(22,22,18))  # one blade down
        draw.ellipse((67,66,105,104),fill=background)
        draw.ellipse((78,77,94,93),fill=(22,22,18))
    for text,y,size in ((entry['category'],30,90),(entry['display_id'],132,99)):
        label=text_image(text,size,(20,22,18,255))
        label.thumbnail((440 if dense else 300,90))
        image.paste(label,(36 if dense else 177,y),label)
    small=text_image('WASTE PACKAGE',30,(24,25,22,255))
    image.paste(small,((512-small.width)//2,228),small)
    rng=np.random.default_rng(entry['appearance_seed'])
    x=30
    while x<480:
        width=int(rng.integers(1,5))
        draw.rectangle((x,278,x+width,330),fill=(24,25,22))
        x+=width+int(rng.integers(1,5))
    image.save(path)
    return {'diffuseColor':path}


def _srgb(linear):
    return tuple(int(round(255*(12.92*c if c <= .0031308 else 1.055*c**(1/2.4)-.055))) for c in linear)


def stencil_texture(entry, paint_linear):
    """Black spray-stencil package ID on the drum's own paint colour (no real organisation text)."""
    safe = entry['paint_color']
    path = ASSETS/f'stencil_{entry["id"]}_{safe}_v2.png'
    if path.exists(): return {'diffuseColor':path}
    ASSETS.mkdir(parents=True,exist_ok=True)
    background = _srgb(paint_linear)
    image = Image.new('RGB',(1024,384),background)
    label = text_image(entry['id'],300,(28,26,22,255))
    label.thumbnail((760,330))
    rng = np.random.default_rng(entry['appearance_seed'])
    # Stencil look: vertical bridges through the letters, slight speckle at the edges.
    arr = np.asarray(label).copy()
    for x in range(0,arr.shape[1],int(rng.integers(55,75))):
        arr[:,x:x+6,3] = 0
    label = Image.fromarray(arr)
    image.paste(label,(60,(384-label.height)//2),label)
    # One small magenta trefoil to the right of the ID (as on the reference drums).
    draw = ImageDraw.Draw(image)
    cx, cy, r_out, r_in = 1024-120, 192, 72, 16
    for angle in (60,180,300):  # standard orientation: one blade down, two up (PIL angles are clockwise)
        draw.pieslice((cx-r_out,cy-r_out,cx+r_out,cy+r_out),angle,angle+60,fill=(196,28,118))
    draw.ellipse((cx-r_in-8,cy-r_in-8,cx+r_in+8,cy+r_in+8),fill=background)
    draw.ellipse((cx-r_in,cy-r_in,cx+r_in,cy+r_in),fill=(196,28,118))
    speck = np.asarray(image).astype(np.int16)
    speck += rng.integers(-6,7,speck.shape[:2])[...,None]
    Image.fromarray(np.clip(speck,0,255).astype(np.uint8)).save(path)
    return {'diffuseColor':path}
