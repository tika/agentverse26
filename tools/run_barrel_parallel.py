"""Four independent GPU workers, distributing the five preview camera views."""
import os
os.environ['ISAAC_RENDER_GPU_COUNT']='1'
os.environ['ISAAC_RENDER_WORKERS']='4'
import io
import json
import shutil
import tarfile
import time
import modal
from run_hall import app,render,ROOT

if __name__=='__main__':
    output=ROOT/'sim/out/barrel_preview'
    output.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    with modal.enable_output(),app.run():
        results=list(render.starmap([('barrel_preview',i,4) for i in range(4)]))
    combined=None;workers=[]
    for i,result in enumerate(results):
        with tarfile.open(fileobj=io.BytesIO(result['archive'])) as archive:
            archive.extractall(ROOT,filter='data')
        directory=output/f'shard_{i:02d}'
        (directory/'run.log').write_text(result['log'])
        assert result['code']==0 and 'BARREL_PREVIEW_OK' in result['log'],str(directory/'run.log')
        report=json.loads((directory/'report.json').read_text())
        runtime=json.loads((directory/'gpu_runtime.json').read_text())
        assert runtime['renderer_active_gpu_count']==1,runtime
        workers.append(runtime)
        if combined is None:
            combined={**report,'views':{}}
        for name,view in report['views'].items():
            destination=output/name
            destination.mkdir(exist_ok=True)
            for source in (directory/name).iterdir():
                if source.is_file():shutil.copy2(source,destination/source.name)
            combined['views'][name]=view
    assert len(combined['views'])==5
    combined.pop('shard',None);combined.pop('shards',None)
    from validate_barrel_preview import validate
    combined['visual_validation']=validate(output)
    combined['render_mode']='four independent single-GPU workers; shared multi-GPU renderer rejected for missing geometry'
    combined['workers']=workers
    combined['parallel_wall_seconds']=round(time.perf_counter()-started,3)
    (output/'gpu_runtime.json').write_text(json.dumps({'mode':'four independent single-GPU workers','total_gpus':4,'workers':workers,'parallel_wall_seconds':combined['parallel_wall_seconds']},indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(combined,indent=2)+'\n')
    print('PARALLEL_PREVIEW_OK',combined['parallel_wall_seconds'],flush=True)
