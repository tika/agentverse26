"""Paired visual recheck evaluation on the warehouse-v3 route."""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / 'sim/warehouse-v3/map.json'
VALIDATION = ROOT / 'docs/validation/yolo26s_expanded_20261108.json'
CLASSES = ('normal', 'rust', 'bulge', 'rust_and_bulge')
UNKNOWN = -1
SPEED, FIRST_DWELL, RECHECK_DWELL = .8, 10., 20.


def route(layout):
    """Snake through the mapped aisles using the end cross aisles."""
    lanes = defaultdict(list)
    for drum in layout['drums']:
        if drum['visible_face']:
            lanes[drum['inspection_route_y']].append(drum)
    left = layout['nodes']['N0_0'][0]
    right = layout['nodes']['N2_0'][0]
    position = tuple(layout['robot_start'][:2])
    path_m, drums = 0., []
    for index, (y, lane) in enumerate(sorted(lanes.items())):
        end = right if index % 2 else left
        entry = (end, y)
        if not index:
            spawn_link = layout['nodes']['front_spawn_link']
            path_m += math.dist(position, spawn_link)
            position = spawn_link
        path_m += abs(position[0] - end) + abs(position[1] - y)
        position = entry
        for drum in sorted(lane, key=lambda d: d['x'], reverse=bool(index % 2)):
            next_position = (drum['x'], y)
            path_m += math.dist(position, next_position)
            position = next_position
            drums.append(drum)
    return drums, path_m


def measured_tables(path):
    """Read the expanded evaluator's per-target class and confidence records."""
    targets = defaultdict(list)
    for record in json.loads(path.read_text()):
        target = record['target']
        kind, category = target['condition'], target['category']
        prediction, confidence = target['predicted'], target['confidence']
        if category not in ('LLW', 'ILW') or kind not in range(4):
            raise ValueError('Unexpected category or ground-truth class')
        if prediction is not None and (prediction not in range(4) or confidence is None or not 0 <= confidence <= 1):
            raise ValueError('Invalid prediction or confidence')
        targets[category, kind].append(prediction if confidence is not None and confidence >= .5 else UNKNOWN)
    if any(not targets[category, kind] for category in ('LLW', 'ILW') for kind in range(4)):
        raise ValueError('Prediction file must cover each of the four classes in both categories')
    return targets


def sample(rng, truth, categories, tables, group_accuracy, uncertain):
    """Return a confident class or UNKNOWN for each candidate view."""
    observations = np.full((*truth.shape, 3), UNKNOWN, dtype=np.int8)
    for category in ('LLW', 'ILW'):
        for kind in range(4):
            mask = (categories == category)[None, :] & (truth == kind)
            count = int(mask.sum())
            if tables is not None:
                observations[mask] = rng.choice(tables[category, kind], size=(count, 3))
                continue
            # Aggregate-constrained sensitivity model. Error direction and
            # confidence are assumptions because the summary lacks raw predictions.
            correct = rng.random((count, 3)) < group_accuracy[category]
            wrong = rng.choice([label for label in range(4) if label != kind], size=(count, 3))
            prediction = np.where(correct, kind, wrong)
            observations[mask] = np.where(rng.random((count, 3)) < uncertain, UNKNOWN, prediction)
    return observations


def paired_metrics(truth, decisions, extra, path_m):
    faulty = truth != 0
    return {
        'follow_up_drums': (decisions == UNKNOWN).sum(axis=1),
        'correctly_classified_faults_pct': 100 * ((decisions == truth) & faulty).sum(axis=1) / faulty.sum(axis=1),
        'faults_marked_normal': ((decisions == 0) & faulty).sum(axis=1),
        'clean_drums_flagged': ((decisions > 0) & ~faulty).sum(axis=1),
        'mission_minutes': (path_m / SPEED + truth.shape[1] * FIRST_DWELL + extra * RECHECK_DWELL) / 60,
    }


def evaluate(observations, truth, path_m, bootstrap):
    initial, retry_a, retry_b = np.moveaxis(observations, -1, 0)
    needs_review = initial == UNKNOWN
    agrees = (retry_a == retry_b) & (retry_a != UNKNOWN)
    adaptive = np.where(needs_review & agrees, retry_a, initial)
    baseline = paired_metrics(truth, initial, np.zeros(len(truth)), path_m)
    revised = paired_metrics(truth, adaptive, 2 * needs_review.sum(axis=1), path_m)
    output = {}
    for name in baseline:
        delta = revised[name] - baseline[name]
        output[name] = {
            'fixed': float(baseline[name].mean()),
            'recheck': float(revised[name].mean()),
            'delta': float(delta.mean()),
            'paired_ci95': np.percentile(delta[bootstrap].mean(axis=1), [2.5, 97.5]).tolist(),
        }
    # Report the pooled drum-level test for comparison with the legacy eval.
    # The paired walk bootstrap above preserves within-walk dependence.
    faulty = truth != 0
    fixed_correct = initial == truth
    recheck_correct = adaptive == truth
    only_fixed = int((faulty & fixed_correct & ~recheck_correct).sum())
    only_recheck = int((faulty & ~fixed_correct & recheck_correct).sum())
    discordant = only_fixed + only_recheck
    p_value = float(binomtest(only_recheck, discordant).pvalue) if discordant else 1.
    # An extreme one-sided discordance gives exact two-sided p = 2 ** (1 - n).
    log10_p = ((1 - discordant) * math.log10(2) if discordant and min(only_fixed, only_recheck) == 0
               else math.log10(p_value) if p_value else None)
    output['mcnemar_correct_fault_classification'] = {
        'both_correct': int((faulty & fixed_correct & recheck_correct).sum()),
        'only_fixed_correct': only_fixed,
        'only_recheck_correct': only_recheck,
        'neither_correct': int((faulty & ~fixed_correct & ~recheck_correct).sum()),
        'p_value': p_value if p_value else None,
        'log10_p_value': log10_p,
        'unit': 'pooled simulated faulty drums',
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', type=Path, help='Expanded checkpoint test_predictions.json')
    parser.add_argument('--walks', type=int, default=2000)
    parser.add_argument('--boot', type=int, default=10000)
    parser.add_argument('--seed', type=int, default=20261108)
    parser.add_argument('--out', type=Path, default=ROOT / 'eval/results/warehouse_v3_summary.json')
    args = parser.parse_args()
    if args.walks < 1 or args.boot < 1:
        parser.error('walks and boot must be positive')
    layout = json.loads(LAYOUT.read_text())
    report = json.loads(VALIDATION.read_text())
    drums, distance = route(layout)
    groups = report['matched_test_results']
    accuracy = {}
    for category, keys in {'LLW': ('legacy_yellow', 'new_yellow'),
                           'ILW': ('legacy_metallic', 'new_blue')}.items():
        parts = [groups[k]['new'] for k in keys]
        accuracy[category] = sum(p['correct'] for p in parts) / sum(p['images'] for p in parts)
    tables = measured_tables(args.predictions) if args.predictions else None
    rng = np.random.default_rng(args.seed)
    # Declared synthetic mix. Both policies receive identical cases and first observations.
    class_mix = [.70, .15, .10, .05]
    truth = rng.choice(len(CLASSES), p=class_mix, size=(args.walks, len(drums)))
    categories = np.array([d['category'] for d in drums])
    bootstrap = rng.integers(0, args.walks, size=(args.boot, args.walks), dtype=np.int32)
    result = dict(walks=args.walks, bootstrap=args.boot, seed=args.seed, drums=len(drums),
                  aisle_count=len({d['inspection_route_y'] for d in drums}), path_m=distance,
                  layout_sha256=hashlib.sha256(LAYOUT.read_bytes()).hexdigest(),
                  expanded_reference_sha256=report['best_sha256'], accuracy_by_category=accuracy,
                  class_mix=dict(zip(CLASSES, class_mix)), drive_m_s=SPEED,
                  first_look_seconds=FIRST_DWELL, seconds_per_extra_look=RECHECK_DWELL,
                  mode='per_class_predictions' if tables is not None else 'aggregate_sensitivity',
                  prediction_file_sha256=hashlib.sha256(args.predictions.read_bytes()).hexdigest() if tables is not None else None,
                  sample_counts={f'{cat}/{CLASSES[k]}': len(v) for (cat, k), v in tables.items()} if tables is not None else None,
                  scenarios={})
    for uncertain in ([None] if tables is not None else [.10, .25, .40]):
        observations = sample(rng, truth, categories, tables, accuracy, uncertain)
        for reuse in (0., .5, 1.):
            correlated = observations.copy()
            # A common bad view can persist across both follow-ups.
            same_view = rng.random(truth.shape) < reuse
            correlated[same_view, 1:] = observations[same_view, :1]
            name = f'unsure_{uncertain}_reuse_{reuse}'
            result['scenarios'][name] = evaluate(correlated, truth, distance, bootstrap)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(f'{len(drums)} drums across {result["aisle_count"]} aisles, {distance:.1f} m planned route')
    print(f'{result["mode"]}: {args.out}')


if __name__ == '__main__':
    main()
