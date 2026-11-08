"""Deploy a separate authenticated NVIDIA LocateAnything service on Modal.

python3 -m modal deploy detector/locateanything/serve.py
"""
from pathlib import Path
import sys
import modal

ROOT=Path(__file__).resolve().parents[2] if modal.is_local() else Path('/workspace')
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,'/workspace/locateanything')
from grounding import MODEL_ID,REVISION,PROMPT,PROMPTS,parse

image=(modal.Image.debian_slim(python_version='3.11')
       .uv_pip_install('torch==2.8.0','torchvision==0.23.0','transformers==4.57.1',
                       'peft==0.17.1','accelerate==1.10.1','numpy==1.26.4','Pillow==11.1.0',
                       'opencv-python-headless==4.11.0.86','decord==0.6.0','lmdb==1.7.5',
                       'fastapi==0.115.12','python-multipart==0.0.20','huggingface_hub==0.36.0')
       .env({'HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false','PYTHONPATH':'/workspace/locateanything'}))
if modal.is_local():
    image=image.add_local_dir(ROOT/'detector'/'locateanything','/workspace/locateanything',copy=True,
                              ignore=['__pycache__/**','*.pyc'])
app=modal.App('agentverse-locateanything')
cache=modal.Volume.from_name('locateanything-model-cache',create_if_missing=True)


@app.cls(image=image,gpu=['H100','RTX-PRO-6000','L40S'],cpu=4,memory=24576,
         volumes={'/model-cache':cache},timeout=300,startup_timeout=900,
         min_containers=0,max_containers=1,scaledown_window=300)
@modal.concurrent(max_inputs=2)
class LocateAnything:
    @modal.enter()
    def load(self):
        import threading,time,torch
        from huggingface_hub import snapshot_download
        from transformers import AutoConfig,AutoModel,AutoProcessor,AutoTokenizer
        started=time.perf_counter()
        self.path=snapshot_download(MODEL_ID,revision=REVISION,cache_dir='/model-cache')
        cache.commit()
        config=AutoConfig.from_pretrained(self.path,trust_remote_code=True)
        for value in (config,config.text_config,config.vision_config):value._attn_implementation='sdpa'
        self.processor=AutoProcessor.from_pretrained(self.path,trust_remote_code=True)
        self.tokenizer=AutoTokenizer.from_pretrained(self.path,trust_remote_code=True)
        self.model=AutoModel.from_pretrained(self.path,config=config,trust_remote_code=True,
            torch_dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda').eval()
        self.lock=threading.Lock();self.gpu=torch.cuda.get_device_name(0)
        print(f'LOCATE_READY {time.perf_counter()-started:.1f}s {self.gpu}',flush=True)

    def infer(self,raw,stamp,query=None):
        import hashlib,io,time,torch
        from PIL import Image
        image=Image.open(io.BytesIO(raw)).convert('RGB')
        if max(image.size)>1280:raise ValueError('Maximum image side is 1280 pixels')
        queries=[query] if query else PROMPTS
        answers=[]
        started=time.perf_counter()
        with self.lock,torch.inference_mode():
            for prompt in queries:
                messages=[{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':prompt}]}]
                text=self.processor.py_apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
                images,videos=self.processor.process_vision_info(messages)
                inputs=self.processor(text=[text],images=images,videos=videos,return_tensors='pt').to('cuda')
                response=self.model.generate(pixel_values=inputs['pixel_values'].to(torch.bfloat16),
                    input_ids=inputs['input_ids'],attention_mask=inputs['attention_mask'],
                    image_grid_hws=inputs.get('image_grid_hws'),tokenizer=self.tokenizer,
                    max_new_tokens=256,use_cache=True,generation_mode='hybrid',temperature=.1,
                    do_sample=False,repetition_penalty=1.1,verbose=False)
                value=response[0] if isinstance(response,tuple) else response
                answers.append(value[0] if isinstance(value,list) else value)
        answer='\n'.join(answers)
        detections,barrels=parse(answer,*image.size)
        return dict(model='LocateAnything-3B',run_id='locateanything3b_'+REVISION[:8],model_revision=REVISION,
            input_sha256=hashlib.sha256(raw).hexdigest(),frame_timestamp=stamp,
            image=dict(width=image.width,height=image.height),detections=detections,barrels=barrels,
            raw_answer=answer,prompts=list(queries),confidence_available=False,
            latency_ms=round((time.perf_counter()-started)*1000,2),gpu=self.gpu)

    @modal.asgi_app(requires_proxy_auth=True)
    def web(self):
        from fastapi import FastAPI,File,Form,UploadFile,HTTPException
        from starlette.concurrency import run_in_threadpool
        api=FastAPI(title='Agentverse LocateAnything',version=REVISION[:8])

        @api.get('/health')
        def health():return dict(status='ready',model=MODEL_ID,revision=REVISION,gpu=self.gpu,
                                 confidence_available=False,backend='transformers BF16 SDPA')

        @api.post('/predict')
        async def predict(file:UploadFile=File(...),frame_timestamp:str|None=Form(None),query:str|None=Form(None)):
            raw=await file.read(4*1024*1024+1)
            if not raw or len(raw)>4*1024*1024:raise HTTPException(413,'Upload must be 1 byte to 4 MiB')
            if query and len(query)>1500:raise HTTPException(400,'Query is too long')
            try:return await run_in_threadpool(self.infer,raw,frame_timestamp,query)
            except ValueError as error:raise HTTPException(400,str(error))
        return api
