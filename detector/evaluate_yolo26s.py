"""Calibrate on validation, freeze operating thresholds, then evaluate the test split."""
import argparse
import hashlib
import json
from pathlib import Path
import time
if __package__:
    from .evaluation_metrics import CLASSES, calibrate, fixed_metrics, match_detections
else:
    from evaluation_metrics import CLASSES, calibrate, fixed_metrics, match_detections


def load_truth(dataset, split):
    from PIL import Image
    truth = []
    images = sorted((dataset/'images'/split).glob('*.jpg'))
    for image in images:
        with Image.open(image) as im:
            width, height = im.size
        for line in (dataset/'labels'/split/(image.stem+'.txt')).read_text().splitlines():
            c, x, y, w, h = map(float, line.split())
            truth.append(dict(image_id=image.stem, class_id=int(c), box=[(x-w/2)*width, (y-h/2)*height, (x+w/2)*width, (y+h/2)*height]))
    return truth, images


def load_predictions(path):
    predictions = []
    for row in json.loads(path.read_text()):
        x, y, w, h = row['bbox']
        # Ultralytics 8.4.207 exports custom-dataset COCO JSON with IDs 1..N.
        # Our YOLO TXT labels and API class IDs remain 0..N-1.
        class_id = int(row['category_id']) - 1
        assert class_id in range(len(CLASSES)), 'Unexpected exported category mapping'
        predictions.append(dict(image_id=str(row['image_id']), class_id=class_id, confidence=float(row['score']), box=[x, y, x+w, y+h]))
    return predictions


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--data', required=True)
    p.add_argument('--dataset', type=Path, required=True)
    a = p.parse_args()
    from ultralytics import YOLO
    import torch
    from PIL import Image, ImageDraw
    started = time.perf_counter()
    destination = a.run_dir/'evaluation'
    destination.mkdir(exist_ok=True)
    progress = json.loads((a.run_dir/'progress.json').read_text())
    progress.update(state='evaluating', epoch=min(progress['epoch'],progress['max_epochs']), eta_seconds=0)
    (a.run_dir/'progress.json').write_text(json.dumps(progress, indent=2))
    (a.run_dir/'evaluation_source.json').write_text(json.dumps({
        name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
        for name in ('evaluate_yolo26s.py','evaluation_metrics.py')}, indent=2))
    model = YOLO(str(a.run_dir/'best.pt'))
    assert list(model.names.values()) == list(CLASSES)
    results = dict(run_id=a.run_dir.name, model='YOLO26s', classes=list(CLASSES), gpu=torch.cuda.get_device_name(0),
                   best_sha256=hashlib.sha256((a.run_dir/'best.pt').read_bytes()).hexdigest(),
                   selection='Best validation fitness from one training run; validation-only thresholds.',
                   scope='Synthetic painted LLW drums; not measured real-world or full-hall performance.',
                   metrics_note='Ultralytics P/R summarize its confidence curve. Fixed-threshold P/R use validation-frozen thresholds and class-wise IoU >= 0.5 matching.')
    cached = {}
    for split in ('val', 'test'):
        progress.update(evaluation_split=split)
        (a.run_dir/'progress.json').write_text(json.dumps(progress, indent=2))
        print('EVAL_PROGRESS '+json.dumps(dict(split=split, state='starting')), flush=True)
        metrics = model.val(data=a.data, split=split, imgsz=640, batch=16, device=0,
                            workers=0, conf=.001, iou=.7, max_det=300, plots=True,
                            save_json=True, save_txt=True, save_conf=True,
                            project=str(destination), name=split, exist_ok=True, verbose=False)
        truth, images = load_truth(a.dataset, split)
        predictions = load_predictions(destination/split/'predictions.json')
        # Validate normalized class IDs and custom image stems after JSON conversion.
        assert predictions and all(r['class_id'] in range(3) and r['image_id'] in {i.stem for i in images} for r in predictions)
        if split == 'val':
            thresholds = calibrate(truth, predictions, len(images))
            (a.run_dir/'thresholds.json').write_text(json.dumps(thresholds, indent=2))
        summary = json.loads(json.dumps(metrics.summary(), default=lambda value: value.item()))
        results[split] = dict(images=len(images), overall={k:float(v) for k,v in metrics.results_dict.items()},
                             per_class=summary, speed_ms=metrics.speed,
                             operating_points=fixed_metrics(truth, predictions, len(images), thresholds))
        cached[split] = (truth, predictions, images)
        print('EVAL_PROGRESS '+json.dumps(dict(split=split, state='complete', overall=results[split]['overall'])), flush=True)
    results['thresholds'] = thresholds
    # Draw actual test predictions, plus difficult images selected by fixed-threshold misses/FPs.
    truth, predictions, images = cached['test']
    errors = {image.stem: 0 for image in images}
    for c, name in enumerate(CLASSES):
        matched, _ = match_detections(truth, predictions, c)
        for row in truth:
            if row['class_id'] == c:
                errors[row['image_id']] += 1
        for row in matched:
            if row['confidence'] >= thresholds[name]['suspect']:
                errors[row['image_id']] += -1 if row['correct'] else 1
    selected = set(list(errors)[:3] + sorted(errors, key=errors.get, reverse=True)[:6])
    preview = destination/'test_examples'
    preview.mkdir(exist_ok=True)
    for image in images:
        if image.stem not in selected:
            continue
        with Image.open(image) as source:
            canvas = source.convert('RGB')
        draw = ImageDraw.Draw(canvas)
        for row in predictions:
            name = CLASSES[row['class_id']]
            if row['image_id'] == image.stem and row['confidence'] >= thresholds[name]['suspect']:
                color = ('#14d7f5', '#ff9800', '#ff40db')[row['class_id']]
                draw.rectangle(row['box'], outline=color, width=2)
                draw.text((row['box'][0], max(0, row['box'][1]-12)), f"{name} {row['confidence']:.2f}", fill=color)
        canvas.save(preview/image.name)
    results['evaluation_seconds'] = time.perf_counter()-started
    (destination/'results.json').write_text(json.dumps(results, indent=2, allow_nan=False))
    text = f"# YOLO26s test results: {a.run_dir.name}\n\n{results['scope']}\n\n"
    text += '| Class | mAP50 | mAP50–95 | Fixed confirm precision | Fixed suspect recall |\n|---|---:|---:|---:|---:|\n'
    for row in results['test']['per_class']:
        name = row['Class']
        op = results['test']['operating_points'][name]
        text += f"| {name} | {row['mAP50']:.4f} | {row['mAP50-95']:.4f} | {op['confirm']['precision']:.4f} | {op['suspect']['recall']:.4f} |\n"
    text += '\nThresholds were chosen on validation, before test evaluation. Full metrics and target flags are in results.json.\n'
    (destination/'results.md').write_text(text)
    progress = json.loads((a.run_dir/'progress.json').read_text())
    progress.update(state='evaluated', test_overall=results['test']['overall'])
    (a.run_dir/'progress.json').write_text(json.dumps(progress, indent=2))
    print('EVAL_COMPLETE '+json.dumps(results), flush=True)


if __name__ == '__main__':
    main()
