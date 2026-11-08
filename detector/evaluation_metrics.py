"""Fixed-threshold detection metrics, independent of PyTorch and the test split."""
from collections import defaultdict

CLASSES = ('drum', 'corrosion', 'bulge')


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / (area_a + area_b - intersection) if area_a + area_b > intersection else 0.0


def match_detections(truth, predictions, class_id):
    """Confidence-ordered, one-to-one matches at IoU >= .5 within the same image/class."""
    targets = defaultdict(list)
    for row in truth:
        if row['class_id'] == class_id:
            targets[row['image_id']].append(row)
    used = defaultdict(set)
    matches = []
    for row in sorted((r for r in predictions if r['class_id'] == class_id), key=lambda r: -r['confidence']):
        options = [(iou(row['box'], t['box']), j) for j, t in enumerate(targets[row['image_id']]) if j not in used[row['image_id']]]
        overlap, index = max(options, default=(0, -1))
        correct = overlap >= .5
        if correct:
            used[row['image_id']].add(index)
        matches.append(dict(row, correct=correct))
    return matches, sum(len(v) for v in targets.values())


def at_threshold(matches, target_count, threshold, image_count):
    kept = [r for r in matches if r['confidence'] >= threshold]
    tp = sum(r['correct'] for r in kept)
    fp = len(kept) - tp
    return dict(threshold=threshold, tp=tp, fp=fp, fn=target_count-tp,
                precision=tp/len(kept) if kept else 0.0,
                recall=tp/target_count if target_count else 0.0,
                false_positives_per_image=fp/image_count)


def calibrate(truth, predictions, image_count):
    """Only call with validation data. Set target flags honestly when unattainable."""
    calibrated = {}
    for class_id, name in enumerate(CLASSES):
        matches, total = match_detections(truth, predictions, class_id)
        grid = [at_threshold(matches, total, i/100, image_count) for i in range(1, 96)]
        high_recall = [r for r in grid if r['recall'] >= .9]
        suspect = max(high_recall, key=lambda r: r['threshold']) if high_recall else grid[0]
        high_precision = [r for r in grid if r['threshold'] >= suspect['threshold'] and r['precision'] >= .9 and r['tp']+r['fp'] >= 5]
        # A fallback is usable, but does not imply the requested precision was achieved.
        confirmed = min(high_precision, key=lambda r: r['threshold']) if high_precision else max(grid, key=lambda r: (2*r['precision']*r['recall']/(r['precision']+r['recall']) if r['precision']+r['recall'] else 0))
        confirmed = next(r for r in grid if r['threshold'] == max(suspect['threshold'], confirmed['threshold']))
        calibrated[name] = dict(suspect=suspect['threshold'], confirm=confirmed['threshold'],
                                recall_target_met=bool(high_recall), precision_target_met=bool(high_precision),
                                validation_suspect=suspect, validation_confirm=confirmed)
    return calibrated


def fixed_metrics(truth, predictions, image_count, thresholds):
    result = {}
    for class_id, name in enumerate(CLASSES):
        matches, total = match_detections(truth, predictions, class_id)
        result[name] = {band: at_threshold(matches, total, thresholds[name][band], image_count) for band in ('suspect', 'confirm')}
        result[name]['ground_truth_instances'] = total
    return result
