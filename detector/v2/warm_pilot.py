"""Persistent Isaac asset renderer. `up` stays running; `run` reuses the same process."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import time
import uuid
import modal

ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
ASSETS=ROOT/'.runtime/drum-pilot15-assets/CANIS_YOLO_DRUM_ASSETS_FOUR_CONDITIONS_V1/warehouse-v3' if modal.is_local() else Path('/assets/warehouse')
SCRIPT=ROOT/'sim/detector_studio_v2/render_pilot.py' if modal.is_local() else Path('/workspace/render_pilot.py')
image=(modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',add_python='3.13',setup_dockerfile_commands=['USER root'])
       .entrypoint([]).env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'})
       .add_local_dir(ASSETS,'/assets/warehouse',copy=True).add_local_file(SCRIPT,'/workspace/render_pilot.py',copy=True))
app=modal.App('canis-condition-warm')
requests=modal.Queue.from_name('canis-condition-warm-requests',create_if_missing=True)
results=modal.Dict.from_name('canis-condition-warm-results',create_if_missing=True)
volume=modal.Volume.from_name('detector-data')

@app.function(image=image,gpu='L40S',cpu=8,memory=32768,timeout=4*60*60,volumes={'/data':volume})
def serve():
    import shutil
    warm=Path('/tmp/canis-warm');warm.mkdir();request_dir=Path('/tmp/canis-warm-requests');request_dir.mkdir()
    initial=[dict(name='warmup',target_id='D320',package_id='C-R-05-T1',angle_deg=0,distance_m=1.65,exposure_scale=1.)]
    Path('/tmp/warmup.json').write_text(json.dumps(initial))
    log=open('/tmp/canis-warm.log','w')
    process=subprocess.Popen(['/isaac-sim/python.sh','/workspace/render_pilot.py','--assets','/assets/warehouse',
        '--views','/tmp/warmup.json','--out',str(warm),'--keep-alive','--allow-root'],stdout=log,stderr=subprocess.STDOUT)
    results['status']={'ready':False,'pid':process.pid}
    while not (warm/'manifest.json').exists():
        if process.poll() is not None:
            results['status']={'ready':False,'error':Path('/tmp/canis-warm.log').read_text(errors='replace')[-3000:]};return
        time.sleep(1)
    results['status']={'ready':True,'pid':process.pid,'scene':'exact four-condition asset pack'}
    print('ISAAC_WARM_READY',flush=True)
    while process.poll() is None:
        try:request=requests.get(timeout=5)
        except queue.Empty:continue
        rid=request['id'];folder=Path('/tmp/canis-warm')/rid
        temp=request_dir/(rid+'.tmp');temp.write_text(json.dumps({'views':request['views'],'out':str(folder)}));temp.rename(temp.with_suffix('.json'))
        while not (folder/'done').exists() and process.poll() is None:time.sleep(.2)
        if folder.exists():
            shutil.copytree(folder,Path('/data/pilots')/rid,dirs_exist_ok=True);volume.commit()
        results[rid]={'volume_path':'/pilots/'+rid,'error':(folder/'error.txt').read_text() if (folder/'error.txt').exists() else None}
    results['status']={'ready':False,'exited':process.returncode}

def up():
    status=results.get('status') or {}
    if status.get('ready'):print('Existing Isaac worker is warm');return
    with modal.enable_output(),app.run(detach=True):call=serve.spawn()
    (ROOT/'.runtime/canis-condition-warm.json').write_text(json.dumps({'call_id':call.object_id}))
    while True:
        status=results.get('status') or {}
        if status.get('ready'):print('ISAAC_WARM_READY; left running until stopped (four-hour session timeout).');return
        if status.get('error'):raise RuntimeError(status['error'])
        time.sleep(2)

def run(path):
    if not (results.get('status') or {}).get('ready'):raise RuntimeError('Run up first')
    rid='warm_'+time.strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:4]
    requests.put({'id':rid,'views':json.loads(Path(path).read_text())})
    while (result:=results.get(rid)) is None:time.sleep(.5)
    out=ROOT/'out/pilots'/rid;out.mkdir(parents=True,exist_ok=True)
    from modal.volume import FileEntryType
    for entry in volume.iterdir(result['volume_path'],recursive=True):
        if entry.type!=FileEntryType.FILE:continue
        target=out/Path(entry.path).relative_to(result['volume_path'].lstrip('/'));target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('wb') as f:
            for chunk in volume.read_file(entry.path):f.write(chunk)
    if result['error']:raise RuntimeError(result['error'])
    print(out)

if __name__=='__main__':
    if sys.argv[1:]==['up']:up()
    elif sys.argv[1:2]==['run'] and len(sys.argv)==3:run(sys.argv[2])
    else:raise SystemExit('Usage: python detector/v2/warm_pilot.py up | run views.json')
