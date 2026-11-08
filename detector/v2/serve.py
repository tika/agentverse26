"""Deploy either comparison candidate without replacing the existing detector API."""
import os,sys,json
from pathlib import Path
import modal
ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
sys.path.insert(0,str(ROOT/'detector'))
from training_image import image
SELECTED=json.loads((ROOT/'detector/v2/selected_model.json').read_text())
SCALE=os.environ.get('CANIS_MODEL_SCALE','s');COMPARISON=os.environ.get('CANIS_COMPARISON_ID',SELECTED['comparison_id'])
if SCALE not in ('n','s') or not COMPARISON.startswith('compare_') or '/' in COMPARISON:
    raise ValueError('Set CANIS_MODEL_SCALE=n|s and CANIS_COMPARISON_ID=compare_TIMESTAMP')
MODEL=f'yolo26{SCALE}'
app=modal.App(os.environ.get('CANIS_API_APP','canis-conditions-'+MODEL))
models=modal.Volume.from_name('detector-models')
image=image.pip_install('fastapi==0.162.2','python-multipart==0.0.33').env({'CANIS_MODEL_SCALE':SCALE,'CANIS_COMPARISON_ID':COMPARISON,'CANIS_API_APP':os.environ.get('CANIS_API_APP','canis-conditions-'+MODEL)})

@app.cls(image=image,gpu='RTX-PRO-6000',cpu=2,memory=8192,volumes={'/models':models},timeout=180,
         min_containers=0,max_containers=1,scaledown_window=120)
@modal.concurrent(max_inputs=4)
class ConditionDetector:
    @modal.enter()
    def load(self):
        import json,hashlib,threading,torch
        import numpy as np
        from ultralytics import YOLO
        models.reload();root=Path('/models/condition_v2')/COMPARISON/MODEL
        self.report=json.loads((root/'results.json').read_text());self.sha=hashlib.sha256((root/'best.pt').read_bytes()).hexdigest()
        assert self.sha==self.report['best_sha256']
        self.model=YOLO(str(root/'best.pt')).to('cuda:0');self.names=['normal','rust','bulge','rust_and_bulge']
        assert list(self.model.names.values())==self.names
        self.gpu=torch.cuda.get_device_name(0);self.lock=threading.Lock()
        self.model.predict(np.zeros((384,384,3),dtype=np.uint8),imgsz=384,device=0,verbose=False)

    @modal.asgi_app(requires_proxy_auth=True)
    def web(self):
        import hashlib,io,time
        from fastapi import FastAPI,UploadFile,File,Form,Query,HTTPException
        from PIL import Image,ImageOps,UnidentifiedImageError
        from starlette.concurrency import run_in_threadpool
        api=FastAPI(title='CANIS '+MODEL+' barrel conditions',version=COMPARISON)
        @api.get('/health')
        def health():return dict(status='ready',model=MODEL,comparison_id=COMPARISON,run_id=COMPARISON+'_'+MODEL,best_sha256=self.sha,
                                 label_schema='whole_barrel_condition_v2',classes=self.names,imgsz=384,gpu=self.gpu,
                                 dataset_id=self.report.get('dataset_id'),test=self.report['test']['overall'])
        def infer(raw,confidence,stamp):
            try:
                with Image.open(io.BytesIO(raw)) as source:
                    if max(source.size)>4096 or source.width*source.height>4096**2:raise HTTPException(413,'Maximum 4096 pixels per side')
                    source.load();frame=ImageOps.exif_transpose(source).convert('RGB')
            except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise HTTPException(400,'Invalid image')
            t=time.perf_counter()
            with self.lock:
                result=self.model.predict(frame,imgsz=384,conf=confidence,iou=.7,max_det=300,device=0,verbose=False)[0]
                boxes=result.boxes.cpu()
            condition_detections=[];barrels=[];legacy=[]
            for i,(xyxy,score,c) in enumerate(zip(boxes.xyxy.tolist(),boxes.conf.tolist(),boxes.cls.tolist())):
                c=int(c);condition=self.names[c];box=[round(v,2) for v in xyxy];score=round(score,6)
                rust=c in (1,3);bulge=c in (2,3)
                condition_detections.append(dict(class_id=c,class_name=condition,confidence=score,bbox_xyxy=box))
                barrels.append(dict(frame_id=f'drum_{i}',bbox_xyxy=box,confidence=score,condition=condition,
                                    corrosion_observed=rust,bulge_observed=bulge))
                # Compatibility projection for the existing robot overlay. These
                # fault boxes cover the whole barrel and never measure rust area.
                for old_id,name,present in ((0,'drum',True),(1,'corrosion',rust),(2,'bulge',bulge)):
                    if present:legacy.append(dict(class_id=old_id,class_name=name,confidence=score,bbox_xyxy=box,
                                                  box_scope='whole_barrel',decision_band='confirm' if score>=.6 else 'suspect'))
            return dict(model=MODEL,run_id=COMPARISON+'_'+MODEL,best_sha256=self.sha,input_sha256=hashlib.sha256(raw).hexdigest(),
                        label_schema='whole_barrel_condition_v2',image=dict(width=frame.width,height=frame.height),frame_timestamp=stamp,
                        condition_detections=condition_detections,barrels=barrels,detections=legacy,
                        latency_ms=round((time.perf_counter()-t)*1000,2),model_speed_ms=result.speed,confidence=confidence)
        @api.post('/predict')
        async def predict(file:UploadFile=File(...),confidence:float=Query(.25,ge=.001,le=1),
                          band:str=Query('fixed',pattern='^(fixed|suspect|confirm)$'),frame_timestamp:str|None=Form(None)):
            raw=await file.read(8*1024*1024+1)
            if not raw or len(raw)>8*1024*1024:raise HTTPException(413,'Upload 1 byte to 8 MiB')
            effective=max(confidence,.6) if band=='confirm' else confidence
            return await run_in_threadpool(infer,raw,effective,frame_timestamp)
        return api
