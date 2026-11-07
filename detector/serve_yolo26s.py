"""Authenticated, scale-to-zero Modal API pinned to one evaluated best checkpoint.

DETECTOR_MODEL_RUN=yolo26s_... modal deploy detector/serve_yolo26s.py
"""
import os
from pathlib import Path
import sys
import modal

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, '/workspace/detector')
from training_image import image

RUN_ID = os.environ.get('DETECTOR_MODEL_RUN', '')
if not RUN_ID or '/' in RUN_ID or not RUN_ID.startswith('yolo26s_'):
    raise ValueError('Set DETECTOR_MODEL_RUN to the evaluated run ID before deployment')

app = modal.App('agentverse-drum-detector-api')
models = modal.Volume.from_name('detector-models', environment_name='main')
serving_image = (image.pip_install('fastapi==0.162.2', 'python-multipart==0.0.33')
                 .env({'DETECTOR_MODEL_RUN': RUN_ID}))


@app.cls(image=serving_image, gpu='L4', cpu=2, memory=8192,
         volumes={'/models': models}, timeout=120,
         min_containers=0, max_containers=1, scaledown_window=60)
@modal.concurrent(max_inputs=4)
class DrumDetector:
    @modal.enter()
    def load(self):
        import hashlib
        import json
        import threading
        import numpy as np
        from ultralytics import YOLO
        models.reload()
        directory = Path('/models/runs')/RUN_ID
        # A deployment can never silently load an unevaluated or different run.
        report = json.loads((directory/'evaluation/results.json').read_text())
        checkpoint = directory/'best.pt'
        self.sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        assert report['best_sha256'] == self.sha
        self.model = YOLO(str(checkpoint)).to('cuda:0')
        self.thresholds = json.loads((directory/'thresholds.json').read_text())
        assert list(self.model.names.values()) == ['drum', 'corrosion', 'bulge']
        self.lock = threading.Lock()
        self.model.predict(np.zeros((640, 640, 3), dtype=np.uint8), imgsz=640, device=0, verbose=False)

    @modal.asgi_app(requires_proxy_auth=True)
    def web(self):
        import io
        import time
        from datetime import datetime, timezone
        from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
        from PIL import Image, ImageOps, UnidentifiedImageError
        from starlette.concurrency import run_in_threadpool

        api = FastAPI(title='Agentverse drum detector', version=RUN_ID,
                      description='YOLO26s RGB boxes. Radiation, temperature, gas inference and robot planning are separate inputs/layers.')

        @api.get('/health')
        def health():
            return dict(status='ready', model='YOLO26s', run_id=RUN_ID, best_sha256=self.sha,
                        classes=self.model.names, thresholds=self.thresholds,
                        auth='Modal proxy token', gpu='L4')

        def predict_image(raw, band, confidence, frame_timestamp):
            try:
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format not in ('JPEG', 'PNG', 'WEBP'):
                        raise HTTPException(415, 'Use JPEG, PNG or WebP')
                    if source.width * source.height > 4096*4096 or max(source.size) > 4096:
                        raise HTTPException(413, 'Image dimensions must be <= 4096 per side and <= 16 MP')
                    source.load()
                    frame = ImageOps.exif_transpose(source).convert('RGB')
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise HTTPException(400, 'Invalid or damaged image')
            started = time.perf_counter()
            floor = confidence if confidence is not None else min(v[band] for v in self.thresholds.values())
            with self.lock:
                result = self.model.predict(frame, imgsz=640, conf=floor, iou=.7, max_det=300,
                                            device=0, verbose=False)[0]
                boxes = result.boxes.cpu()
            detections = []
            for xyxy, score, class_id in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
                name = self.model.names[int(class_id)]
                cutoff = confidence if confidence is not None else self.thresholds[name][band]
                if score < cutoff:
                    continue
                detections.append(dict(class_id=int(class_id), class_name=name, confidence=round(score, 6),
                                       bbox_xyxy=[round(v, 2) for v in xyxy],
                                       decision_band='confirm' if score >= self.thresholds[name]['confirm'] else 'suspect'))
            return dict(model='YOLO26s', run_id=RUN_ID, best_sha256=self.sha,
                        received_at=datetime.now(timezone.utc).isoformat(), frame_timestamp=frame_timestamp,
                        image=dict(width=frame.width, height=frame.height), detections=detections,
                        latency_ms=round((time.perf_counter()-started)*1000, 2), model_speed_ms=result.speed,
                        operating_mode=band, confidence_override=confidence)

        @api.post('/predict')
        async def predict(file: UploadFile = File(...),
                          band: str = Query('suspect', pattern='^(suspect|confirm)$'),
                          confidence: float | None = Query(None, ge=.001, le=1),
                          frame_timestamp: str | None = Form(None)):
            raw = await file.read(8*1024*1024+1)
            if not raw or len(raw) > 8*1024*1024:
                raise HTTPException(413, 'Image must contain 1 byte to 8 MiB')
            return await run_in_threadpool(predict_image, raw, band, confidence, frame_timestamp)

        return api
