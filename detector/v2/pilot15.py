"""Bounded 15-image, four-condition pilot on four independent L40S workers."""
import io
import json
from pathlib import Path
import subprocess
import tarfile
import time
import modal

ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
ASSETS=(ROOT/'.runtime/drum-pilot15-assets/CANIS_YOLO_DRUM_ASSETS_FOUR_CONDITIONS_V1/warehouse-v3') if modal.is_local() else Path('/assets/warehouse')
SCRIPT=(ROOT/'sim/detector_studio_v2/render_pilot.py') if modal.is_local() else Path('/workspace/render_pilot.py')
RUN='conditions15_'+time.strftime('%Y%m%dT%H%M%SZ')
catalog=json.loads((ASSETS/'sample_catalog.json').read_text())
sample={d['condition']:d for d in catalog if d['category']=='LLW' and d['tier']==1}
views=[]
for condition in ('normal','corrosion_only','bulge_only','bulge_and_corrosion'):
    target=sample[condition]
    for angle in (-45,0,45):
        i=len(views);views.append(dict(name=f'{i+1:02d}_{condition}_{angle:+d}',target_id=Path(target['prim_path']).name,
            package_id=target['package_id'],angle_deg=angle,distance_m=1.65,exposure_scale=(.9,1.,1.1)[i%3]))
for condition,angle in (('corrosion_only',-60),('bulge_only',60),('bulge_and_corrosion',-35)):
    target=sample[condition];views.append(dict(name=f'{len(views)+1:02d}_{condition}_close',target_id=Path(target['prim_path']).name,
        package_id=target['package_id'],angle_deg=angle,distance_m=1.1,exposure_scale=1.))
image=(modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',setup_dockerfile_commands=['USER root'])
       .entrypoint([]).env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'})
       .add_local_dir(ASSETS,'/assets/warehouse',copy=True)
       .add_local_file(SCRIPT,'/workspace/render_pilot.py',copy=True))
app=modal.App('canis-condition-pilot15')
volume=modal.Volume.from_name('detector-data')

@app.function(image=image,gpu='L40S',cpu=8,memory=32768,timeout=600,max_containers=4,
              volumes={'/data':volume},single_use_containers=True)
def render(shard,selected,run_id):
    import shutil
    out=Path('/tmp/pilot');out.mkdir();Path('/tmp/views.json').write_text(json.dumps(selected))
    started=time.perf_counter()
    with open('/tmp/pilot.log','w') as log:
        result=subprocess.run(['/isaac-sim/python.sh','/workspace/render_pilot.py','--assets','/assets/warehouse',
                               '--views','/tmp/views.json','--out',str(out),'--allow-root'],stdout=log,stderr=subprocess.STDOUT,timeout=540)
    shutil.copy2('/tmp/pilot.log',out/'isaac.log')
    (out/'hardware.json').write_text(json.dumps(dict(gpu=subprocess.check_output(['nvidia-smi','-L'],text=True),
        isaac=Path('/isaac-sim/VERSION').read_text().strip(),wall_s=round(time.perf_counter()-started,3),returncode=result.returncode)))
    shutil.copytree(out,Path('/data/pilots')/run_id/f'shard_{shard}',dirs_exist_ok=True);volume.commit()
    blob=io.BytesIO()
    with tarfile.open(fileobj=blob,mode='w:gz') as archive:archive.add(out,arcname=f'shard_{shard}')
    return dict(code=result.returncode,archive=blob.getvalue(),tail=Path('/tmp/pilot.log').read_text(errors='replace')[-2000:])

@app.local_entrypoint()
def main():
    from PIL import Image,ImageDraw,ImageFont
    out=ROOT/'out/pilots'/RUN;out.mkdir(parents=True,exist_ok=True)
    (out/'requested_views.json').write_text(json.dumps(views,indent=2))
    started=time.perf_counter();results=list(render.starmap([(i,views[i::4],RUN) for i in range(4)],order_outputs=True))
    frames=[]
    for result in results:
        with tarfile.open(fileobj=io.BytesIO(result['archive'])) as archive:archive.extractall(out,filter='data')
        if result['code']:print(result['tail']);raise RuntimeError('Pilot shard failed; outputs retained at '+str(out))
    for path in out.glob('shard_*/manifest.json'):
        frames.extend({**f,'folder':str(path.parent.relative_to(out))} for f in json.loads(path.read_text())['frames'])
    frames.sort(key=lambda f:f['name']);assert len(frames)==15
    sheet=Image.new('RGB',(5*384,3*430),'#121a21');draw=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=18)
    for i,f in enumerate(frames):
        x=(i%5)*384;y=(i//5)*430
        sheet.paste(Image.open(out/f['folder']/'overlays'/f"{f['name']}.png"),(x,y))
        draw.text((x+5,y+386),f"{f['name'].split('_')[0]}  {f['condition']}",font=font,fill='white')
        draw.text((x+5,y+407),f"{f['angle_deg']:+d} deg | {f['distance_m']:.2f} m | {f['package_id']}",font=font,fill='#b9c9d6')
    sheet.save(out/'contact_sheet.jpg',quality=94)
    summary=dict(run_id=RUN,frames=frames,resolution=[384,384],worker_count=4,wall_s=round(time.perf_counter()-started,3),
                 volume_path=f'detector-data:/pilots/{RUN}/',source_asset_revision='e4d31c8a323708db4af2f94e4396ca4872457eff',
                 scope='15-image visual and annotation pilot only; no full generation or training')
    (out/'pilot.json').write_text(json.dumps(summary,indent=2))
    with volume.batch_upload(force=True) as batch:
        batch.put_file(out/'pilot.json',f'/pilots/{RUN}/pilot.json');batch.put_file(out/'contact_sheet.jpg',f'/pilots/{RUN}/contact_sheet.jpg')
    print('PILOT_COMPLETE',out,'wall_s',summary['wall_s'],flush=True)
