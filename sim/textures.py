"""Seeded, cached textures made with numpy and PIL; no downloaded assets."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent / 'assets' / 'generated'


def noise(rng, size=1024):
    result = np.zeros((size, size), dtype=np.float32)
    for cells, weight in ((8, .50), (32, .27), (128, .15), (512, .08)):
        small = Image.fromarray(np.uint8(rng.random((cells, cells)) * 255))
        result += np.asarray(small.resize((size, size), Image.Resampling.BICUBIC), dtype=np.float32) / 255 * weight
    return result


def maps(name, color, roughness, height):
    paths = {}
    dy, dx = np.gradient(height)
    normals = np.dstack((-dx*5, dy*5, np.ones_like(dx)))
    normals /= np.linalg.norm(normals, axis=2, keepdims=True)
    arrays = {'diffuseColor': color, 'roughness': roughness * 255, 'normal': (normals*.5+.5)*255}
    for channel, array in arrays.items():
        path = ASSETS / f'{name}_{channel}.png'
        Image.fromarray(np.uint8(np.clip(array, 0, 255))).save(path)
        paths[channel] = path
    return paths


def text_image(text, size, color):
    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', size)
    except OSError:
        font = ImageFont.load_default(size=size)
    bounds = font.getbbox(text)
    image = Image.new('RGBA', (bounds[2]-bounds[0]+8, bounds[3]-bounds[1]+8))
    ImageDraw.Draw(image).text((4-bounds[0], 4-bounds[1]), text, font=font, fill=color)
    return image


def floor_texture(rng, name):
    n = 1024
    grain = noise(rng)
    rgb = np.array([158, 163, 160])[None,None,:] + (grain[:,:,None]-.5)*29
    rgb += rng.normal(0, .7, (n, n, 1))
    image = Image.fromarray(np.uint8(np.clip(rgb, 0, 255))).convert('RGBA')
    marks = Image.new('RGBA', (n, n))
    draw = ImageDraw.Draw(marks)
    xy = lambda x,y: (round(x/20*n), round((12-y)/12*n))
    # V2: only dry rectangular repairs; release-looking stains are forbidden.
    for x,y,w,h in ((5.7,.6,1.0,.55),(14.7,11.3,1.1,.6),(8.2,6.5,.6,.5)):
        shade = int(rng.integers(144,172))
        draw.rectangle([xy(x-w/2,y+h/2),xy(x+w/2,y-h/2)],fill=(shade,shade+3,shade,180),outline=(115,120,115,60))
    for x,y in ((4.5,2), (13,10), (16,6)):
        for offset in (-.24,.24):
            draw.line([xy(x-1,y+offset),xy(x+1,y+offset+.1)], fill=(48,53,52,26), width=3)
    for _ in range(45):
        x,y = rng.uniform(0,20),rng.uniform(0,12)
        draw.line([xy(x,y),xy(x+.45,y+.04)],fill=(210,213,208,12),width=1)
    for edge in (1,3,5,7,9,11):
        for start,end in ((2.5,9), (11,17.5)):
            draw.rectangle([xy(start,edge+.05), xy(end,edge-.05)], fill=(210,166,35,230))
    # Worn-thin paint at the cross-aisle approaches.
    for x in (2.6,8.8,11.2,17.4):
        for edge in (1,3,5,7,9,11):
            draw.line([xy(x-.07,edge),xy(x+.07,edge)],fill=(156,160,154,190),width=3)
    # A 0.5 m-wide LLW/ILW boundary stripe at x=10.
    yy,xx = np.mgrid[:n,:n]
    xworld, yworld = xx/n*20, (1-yy/n)*12
    mask = (abs(xworld-10)<.25) & (yworld>.5) & (yworld<11.5)
    hatch = ((xworld+yworld)/.22).astype(int) % 2 == 0
    stripes = np.asarray(marks).copy()
    stripes[mask & hatch] = (212,169,35,240)
    stripes[mask & ~hatch] = (35,37,35,240)
    marks = Image.fromarray(stripes)
    image = Image.alpha_composite(image, marks).convert('RGB')
    rough = np.clip(.48 + (grain-.5)*.13, .4, .55)
    return maps(name, np.asarray(image), rough, grain*.3)


def wall_texture(rng, name):
    n = 1024
    grain = noise(rng)
    color = np.array([161,161,150])[None,None,:] + (grain[:,:,None]-.5)*38
    image = Image.fromarray(np.uint8(np.clip(color,0,255))).convert('RGBA')
    overlay = Image.new('RGBA',(n,n))
    draw = ImageDraw.Draw(overlay)
    # One tile represents 4.8 m along a wall and its full 6 m height.
    xy = lambda x,z: (round(x/4.8*n),round((6-z)/6*n))
    for x in (0,2.4,4.8):
        draw.line([xy(x,0),xy(x,6)], fill=(62,64,57,75),width=3)
    for z in (1.2,2.4,3.6,4.8):
        draw.line([xy(0,z),xy(4.8,z)], fill=(68,69,63,65),width=2)
    for x in (.6,1.8,3,4.2):
        for z in (.6,1.8,3,4.2,5.4):
            px,py = xy(x,z)
            draw.ellipse((px-3,py-2,px+3,py+2),fill=(48,49,44,170))
            if rng.random() < .3:
                length = int(rng.uniform(22,110))
                for offset in range(length):
                    draw.line((px-2,py+offset,px+2,py+offset),fill=(76,79,75,int(38*(1-offset/length))))
    image = Image.alpha_composite(image,overlay)
    array = np.asarray(image.convert('RGB')).copy()
    # The lower 1.5 m has a straight-edged, washable pale green coating.
    array[768:] = np.clip(np.array([137,151,139]) + (grain[768:, :, None]-.5)*17,0,255)
    array[767:770] = (103,118,104)
    rough = np.where(np.arange(n)[:,None]>=768,.52,.81) + (grain-.5)*.07
    return maps(name,array,rough,grain*.45)


def sign(name, lines, background=(224,185,38), trefoil=False):
    path = ASSETS / (name+'.png')
    if path.exists():
        return {'diffuseColor':path}
    image = Image.new('RGB',(512,512),background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8,8,503,503),outline=(35,35,29),width=8)
    if trefoil:
        center, radius = (256,165),105
        bounds=(center[0]-radius,center[1]-radius,center[0]+radius,center[1]+radius)
        for angle in (30,150,270): draw.pieslice(bounds,angle,angle+60,fill=(22,22,18))
        draw.ellipse((221,130,291,200),fill=background)
        draw.ellipse((242,151,270,179),fill=(22,22,18))
    y = 290 if trefoil else 95
    for line in lines:
        text = text_image(line,52,(24,25,22,255))
        text.thumbnail((450,85))
        image.paste(text,((512-text.width)//2,y),text)
        y += 64
    image.save(path)
    return {'diffuseColor':path}


def generate_textures(seed=42):
    ASSETS.mkdir(parents=True,exist_ok=True)
    floor_name, wall_name = f'floor_s{seed}_v2',f'wall_s{seed}_v2'
    expected = lambda name: {key:ASSETS/f'{name}_{key}.png' for key in ('diffuseColor','roughness','normal')}
    rng = np.random.default_rng(seed)
    # Generate banks independently so cache presence never changes the seed sequence.
    for name, function, local_seed in ((floor_name,floor_texture,int(rng.integers(2**31))),
                                      (wall_name,wall_texture,int(rng.integers(2**31)))):
        if not all(path.exists() for path in expected(name).values()):
            function(np.random.default_rng(local_seed),name)
    shutter = ASSETS/'roller_v1.png'
    if not shutter.exists():
        yy,xx = np.mgrid[:512,:512]
        bands = np.sin(yy/16*2*np.pi)*9 - ((yy%16)<2)*27
        pixels = np.clip(np.array([133,141,143])[None,None,:]+bands[:,:,None],0,255)
        Image.fromarray(np.uint8(pixels)).save(shutter)
    drain = ASSETS/'drain_v2.png'
    if not drain.exists():
        grate = Image.new('RGB',(256,256),(42,47,46))
        draw = ImageDraw.Draw(grate)
        draw.rectangle((8,8,247,247),outline=(108,114,109),width=12)
        for point in range(35,240,28):
            draw.line((point,20,point,236),fill=(112,119,112),width=5)
            draw.line((20,point,236,point),fill=(112,119,112),width=5)
        grate.save(drain)
    labels = {}
    for zone,title in (('llw','LLW STORE - ZONE A'),('ilw','ILW STORE - ZONE B')):
        path = ASSETS/f'floor_{zone}_v3.png'
        if not path.exists():
            text_image(title,64,(219,210,159,230)).resize((1024,128)).save(path)
        labels['floor_'+zone] = {'diffuseColor':path,'opacity':path}
    bank = {'floor':expected(floor_name),'wall':expected(wall_name),
            'roller':{'diffuseColor':shutter},
            'drain':{'diffuseColor':drain}, **labels,
            'radiation':sign('radiation_v1',['CAUTION','RADIATION','CONTROLLED AREA'],trefoil=True),
            'llw':sign('zone_llw_v1',['LLW','STORE - ZONE A'],trefoil=True),
            'ilw':sign('zone_ilw_v1',['ILW','STORE - ZONE B'],trefoil=True),
            'fire':sign('fire_v1',['FIRE','POINT'],background=(199,65,46))}
    for name,channels in bank.items():
        for channel in channels:
            provided = ASSETS.parent/'provided'/f'{name}_{channel}.png'
            if provided.exists(): channels[channel] = provided
    return bank
