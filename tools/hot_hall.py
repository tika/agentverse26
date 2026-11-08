"""Hot hall worker on Modal: build the hall and walking Spot once, then run edits in seconds.

    python tools/hot_hall.py up                    # start (about 4 min to HOT_READY), stays up 4 h
    python tools/hot_hall.py run scripts/hot/walk_aisle.py   # exec on the live stage, fetch mp4s
    python tools/hot_hall.py run lib.py scenario.py          # several files run as one request
    python tools/hot_hall.py down

Request scripts run inside sim/hot_server.py; see its docstring for the helpers they get.
Changes to sim/*.py need `down` and `up`, because the image copies sim/ at start.
"""
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tarfile
import threading
import time
import uuid
import modal

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime/hot.json'
OUT = ROOT / 'out/hot'
# Same image recipe as tools/run_hall.py, which renders hall textures correctly.
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0',
                                   add_python='3.13', setup_dockerfile_commands=['USER root'])
         .entrypoint([])
         .pip_install('imageio[ffmpeg]')
         .env({'ACCEPT_EULA': 'Y', 'PRIVACY_CONSENT': 'N', 'NVIDIA_DRIVER_CAPABILITIES': 'all',
               'HOT_SPAWN_X':os.environ.get('HOT_SPAWN_X','10'), 'HOT_SPAWN_Y':os.environ.get('HOT_SPAWN_Y','6')})
         .add_local_dir(ROOT / 'sim', '/workspace/sim', copy=True,
                        ignore=['out/**', '__pycache__/**', '**/__pycache__/**', '**/*.pyc', '*.usda']))
app = modal.App('agentverse-hot-hall')
requests = modal.Queue.from_name('agentverse-hot-requests', create_if_missing=True)
results = modal.Dict.from_name('agentverse-hot-results', create_if_missing=True)
services = modal.Dict.from_name('agentverse-hot-services', create_if_missing=True)
mission_runs = modal.Volume.from_name('agentverse-mission-runs', create_if_missing=True)


def _encode(folder):
    import imageio.v2 as imageio
    for frames in sorted(folder.rglob('frames')):
        images = sorted(frames.glob('*.jpg'))
        if images:
            with imageio.get_writer(frames.parent.with_suffix('.mp4'), fps=12, codec='libx264',
                                    quality=7, macro_block_size=1, ffmpeg_params=['-movflags','+faststart']) as writer:
                for path in images:
                    writer.append_data(imageio.imread(path))
        for path in images:
            path.unlink()
        frames.rmdir()


@app.function(image=image, gpu=['RTX-PRO-6000','L40S','L4'], cpu=8, memory=32768, timeout=4 * 60 * 60,
              volumes={'/mission-runs':mission_runs},
              # Unconditional dependency; external Cosmos credentials are refreshed from the private Dict.
              secrets=[modal.Secret.from_name('drum-inference', required_keys=['DETECTOR_API_URL','DETECTOR_API_KEY','DETECTOR_API_SECRET'])])
def serve():
    hot = Path('/tmp/hot')
    log = open('/tmp/hot.log', 'w')
    # A teammate's external Cosmos service can be configured without restarting
    # Isaac. Credentials stay in a private worker file, outside recorded outputs.
    def refresh_services():
        config=services.get('cosmos') or {}
        hot.mkdir(parents=True,exist_ok=True)
        path=hot/'services.json'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as output:json.dump(config,output)
    refresh_services()
    # Default Cosmos endpoint: our vLLM deployment (tools/cosmos_vllm.py); `cosmos-config` can override it.
    cosmos_url = (services.get('cosmos') or {}).get('COSMOS_URL') or os.environ.get('COSMOS_URL','')
    if not cosmos_url:
        cosmos_url = modal.Function.from_name('agentverse-cosmos-vllm', 'serve').get_web_url()
    process = subprocess.Popen(['/isaac-sim/python.sh', '/workspace/sim/hot_server.py', '--allow-root'],
                               cwd='/workspace/sim', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               env={**os.environ, 'COSMOS_URL': cosmos_url,
                                    'COSMOS_CONFIG_FILE': str(hot / 'services.json')})

    def pump():
        for line in process.stdout:
            log.write(line)
            log.flush()
            if 'HOT_READY' in line or '[hot]' in line or 'Traceback' in line:
                print(line, end='', flush=True)
            if 'HOT_READY' in line:
                results['_status'] = {'ready': True, 'line': line.strip(), 'time': time.time()}
    threading.Thread(target=pump, daemon=True).start()
    results['_status'] = {'ready': False, 'time': time.time()}
    while process.poll() is None:
        try:
            request = requests.get(timeout=5)
        except queue.Empty:
            continue
        if request is None:
            continue
        rid = request['id']
        refresh_services()
        (hot / 'req').mkdir(parents=True, exist_ok=True)
        staged = hot / 'req' / f'{rid}.tmp'
        staged.write_text(request['source'])
        staged.rename(staged.with_suffix('.py'))
        done = hot / 'out' / rid / 'done'
        committed=0.
        while not done.exists() and process.poll() is None:
            # Isaac writes atomic checkpoints. Commit them without importing Modal
            # or ML dependencies into Isaac's bundled Python interpreter.
            if time.monotonic()-committed>15:
                mission_runs.commit();committed=time.monotonic()
            time.sleep(0.2)
        folder = hot / 'out' / rid
        if folder.exists():
            _encode(folder)
            import shutil
            shutil.copytree(folder,Path('/mission-runs/runs')/rid,dirs_exist_ok=True)
            mission_runs.commit()
        tail = Path('/tmp/hot.log').read_text(errors='replace')[-6000:]
        # Keep long recordings on the volume rather than serializing a large MP4 into a Dict.
        results[rid] = {'volume_path': '/runs/'+rid, 'alive': process.poll() is None, 'log_tail': tail}
    results['_status'] = {'ready': False, 'exited': process.returncode,
                          'log_tail': Path('/tmp/hot.log').read_text(errors='replace')[-9000:]}


def up():
    with modal.enable_output():
        with app.run(detach=True):
            call = serve.spawn()
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({'call_id': call.object_id, 'started': time.time()}))
    print('Starting hot worker', call.object_id, '- waiting for HOT_READY', flush=True)
    while True:
        status = results.get('_status') or {}
        if status.get('ready'):
            print(status['line'], flush=True)
            return
        if 'exited' in status:
            print(status.get('log_tail', ''))
            raise SystemExit('Hot worker exited during startup')
        time.sleep(10)


def run(*scripts, timeout_s=7200):
    rid = time.strftime('%H%M%S-') + Path(scripts[-1]).stem + '-' + uuid.uuid4().hex[:4]
    status = results.get('_status') or {}
    if not status.get('ready'):
        raise SystemExit('Hot worker is not ready; run `python tools/hot_hall.py up`')
    started = time.perf_counter()
    requests.put({'id': rid, 'source': '\n'.join(Path(script).read_text() for script in scripts)})
    while (result := results.get(rid)) is None:
        if time.perf_counter() - started > timeout_s:
            raise SystemExit(f'No result for {rid} after {timeout_s}s')
        time.sleep(1)
    results.pop(rid)
    OUT.mkdir(parents=True, exist_ok=True)
    folder = OUT / rid
    if 'volume_path' in result:
        from modal.volume import FileEntryType
        folder.mkdir(parents=True,exist_ok=True)
        for entry in mission_runs.iterdir(result['volume_path'],recursive=True):
            relative=Path(entry.path.lstrip('/')).relative_to(result['volume_path'].lstrip('/'))
            target=folder/relative
            if entry.type==FileEntryType.DIRECTORY:
                target.mkdir(parents=True,exist_ok=True)
            elif entry.type==FileEntryType.FILE:
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('wb') as output:
                    for chunk in mission_runs.read_file(entry.path):output.write(chunk)
    else:  # Compatibility with an already-running worker from the earlier recording.
        with tarfile.open(fileobj=io.BytesIO(result['archive'])) as archive:
            archive.extractall(OUT, **({'filter': 'data'} if sys.version_info >= (3, 12) else {}))
    print(f'{rid}: {time.perf_counter() - started:.1f}s round trip -> {folder}')
    error = folder / 'error.txt'
    if error.exists():
        print(error.read_text())
        print(result['log_tail'][-3000:])
        raise SystemExit(1)
    videos = sorted(folder.glob('*.mp4'))
    for video in videos:
        print('  video', video)
    if videos and sys.platform == 'darwin' and not os.environ.get('HOT_NO_OPEN'):
        subprocess.run(['open', *map(str, videos)])


def down():
    call_id = json.loads(STATE.read_text())['call_id']
    modal.FunctionCall.from_id(call_id).cancel()
    results['_status'] = {'ready': False, 'stopped': time.time()}
    print('Stopped', call_id)


def configure_cosmos(path):
    """Load a private JSON or dotenv file; never print credentials."""
    import shlex
    text=Path(path).read_text()
    if text.lstrip().startswith('{'):
        config=json.loads(text)
    else:
        config={}
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            key,value=line.removeprefix('export ').split('=',1)
            parts=shlex.split(value)
            config[key.strip()]=parts[0] if parts else ''
    allowed=('COSMOS_URL','VLLM_API_KEY','COSMOS_MODEL')
    config={key:str(value) for key,value in config.items() if key in allowed}
    if not config.get('COSMOS_URL','').startswith('https://'):
        raise ValueError('COSMOS_URL must be an HTTPS base URL')
    services['cosmos']=config
    print('Configured external Cosmos endpoint; credentials not displayed')


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    if command == 'up':
        up()
    elif command == 'run' and len(sys.argv) > 2:
        run(*sys.argv[2:])
    elif command == 'down':
        down()
    elif command == 'cosmos-config' and len(sys.argv)==3:
        configure_cosmos(sys.argv[2])
    else:
        raise SystemExit(__doc__)
