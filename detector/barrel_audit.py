"""Audit barrel-level condition decisions separately from individual patch localization.

No GPU or retraining. Uses frozen predictions, observed GT boxes and identity metadata
only for evaluation. Inventory IDs never enter model inputs or predictions.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

if __package__:
    from .evaluation_metrics import iou
    from .evaluate_yolo26s import load_predictions
else:
    from evaluation_metrics import iou
    from evaluate_yolo26s import load_predictions


def intersection(a, b):
    return max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))


def assign_conditions(drums, faults, thresholds):
    """Pure box postprocessing, without GT identity or fault flags."""
    states = [dict(corrosion=False, bulge=False) for _ in drums]
    for fault in faults:
        name = 'corrosion' if fault['class_id'] == 1 else 'bulge'
        if fault['confidence'] < thresholds[fault['class_id']]:
            continue
        box = fault['box']
        options = []
        for index, drum in enumerate(drums):
            if name == 'bulge':
                overlap = iou(box, drum['box'])
                if overlap >= .5:
                    options.append((overlap, 0, index))
            else:
                x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
                d = drum['box']
                area = max(1, (box[2]-box[0])*(box[3]-box[1]))
                overlap = intersection(box,d)/area
                if d[0] <= x <= d[2] and d[1] <= y <= d[3] and overlap >= .5:
                    # For overlapping drum rectangles, prefer containment, then the
                    # smaller drum extent. This is an approximate 2D association.
                    options.append((overlap, -(d[2]-d[0])*(d[3]-d[1]), index))
        if options:
            states[max(options)[2]][name] = True
    return states


def audit(dataset, predictions_path, split, thresholds):
    by_image = defaultdict(list)
    for row in load_predictions(predictions_path):
        by_image[row['image_id']].append(row)
    count = defaultdict(int)
    unique = defaultdict(lambda: dict(detected=False, correct_any_view=False,
                                      clean_false_alert_any_view=False, rusty=False,
                                      rust_found_any_view=False))
    rows = []
    for path in sorted((dataset/'metadata'/split).glob('*.json')):
        data = json.loads(path.read_text())
        gt_drums = [b for b in data['boxes'] if b['class_id'] == 0]
        gt_rust = [b for b in data['boxes'] if b['class_id'] == 1]
        bulging = {b['internal_id'] for b in data['boxes'] if b['class_id'] == 2}
        rusty = {b['internal_id'] for b in gt_rust}
        flags = {d['id']: d for d in data['drums']}
        predictions = by_image[path.stem]
        predicted_drums = sorted((r for r in predictions if r['class_id'] == 0 and r['confidence'] >= thresholds[0]), key=lambda r:-r['confidence'])
        states = assign_conditions(predicted_drums, [r for r in predictions if r['class_id'] in (1,2)], thresholds)
        # One-to-one matching between predicted physical drums and GT drums.
        assigned = {}
        used = set()
        for index, drum in enumerate(predicted_drums):
            overlap, target = max(((iou(drum['box'], gt['xyxy']), j) for j, gt in enumerate(gt_drums) if j not in used), default=(0,-1))
            if overlap >= .5:
                assigned[target] = index
                used.add(target)
        # Independent patch localization. A correct barrel decision does not make
        # every unmatched patch a TP: patch boxes must still reach IoU >= .5.
        patch_matches = set()
        for predicted in sorted((r for r in predictions if r['class_id'] == 1 and r['confidence'] >= thresholds[1]), key=lambda r:-r['confidence']):
            overlap, target = max(((iou(predicted['box'], gt['xyxy']), j) for j,gt in enumerate(gt_rust) if j not in patch_matches), default=(0,-1))
            if overlap >= .5:
                patch_matches.add(target)
        count['visible_drum_instances'] += len(gt_drums)
        count['detected_drum_instances'] += len(assigned)
        count['false_positive_drum_boxes'] += len(predicted_drums)-len(assigned)
        count['visible_patch_boxes'] += len(gt_rust)
        count['matched_patch_boxes'] += len(patch_matches)
        for j, gt in enumerate(gt_drums):
            identity = gt['internal_id']
            physical = unique[(path.stem.split('_')[1],identity)]
            physical['rusty'] = flags[identity]['rust']
            detected = j in assigned
            physical['detected'] |= detected
            state = states[assigned[j]] if detected else dict(corrosion=False,bulge=False)
            visible_rust = identity in rusty
            known_clean = not flags[identity]['rust']
            evaluable = visible_rust or known_clean
            count['rust_evaluable_instances'] += evaluable
            count['rust_ambiguous_instances'] += not evaluable
            correct_rust = evaluable and detected and state['corrosion'] == visible_rust
            correct_bulge = detected and state['bulge'] == (identity in bulging)
            correct_all = correct_rust and correct_bulge
            count['correct_rust_condition_instances'] += correct_rust
            count['correct_bulge_condition_instances'] += correct_bulge
            count['correct_both_conditions_instances'] += correct_all
            if evaluable:
                count['both_conditions_denominator'] += 1
                physical['correct_any_view'] |= correct_all
            if visible_rust:
                count['rusty_barrel_instances'] += 1
                count['rusty_barrels_flagged'] += detected and state['corrosion']
                physical['rust_found_any_view'] |= detected and state['corrosion']
            elif known_clean:
                count['clean_barrel_instances'] += 1
                count['clean_false_rust_alerts'] += detected and state['corrosion']
                physical['clean_false_alert_any_view'] |= detected and state['corrosion']
            indices = [k for k,b in enumerate(gt_rust) if b['internal_id'] == identity]
            matched = sum(k in patch_matches for k in indices)
            if visible_rust and correct_rust:
                count['correct_rusty_barrels_patch_total'] += len(indices)
                count['correct_rusty_barrels_patches_matched'] += matched
            if visible_rust and correct_all:
                count['both_conditions_correct_rusty_barrels'] += 1
                count['both_correct_patch_total'] += len(indices)
                count['both_correct_patches_matched'] += matched
            rows.append(dict(image=path.stem, drum_id=identity, detected=detected,
                             visible_rust=visible_rust, physical_rust=flags[identity]['rust'],
                             gt_bulge=identity in bulging, predicted_rust=state['corrosion'],
                             predicted_bulge=state['bulge'], evaluable=evaluable,
                             both_correct=correct_all, patches=len(indices), patches_matched=matched))
    for prefix,total,found in [('all','visible_patch_boxes','matched_patch_boxes'),
                               ('rust_correct','correct_rusty_barrels_patch_total','correct_rusty_barrels_patches_matched'),
                               ('both_correct','both_correct_patch_total','both_correct_patches_matched')]:
        count[prefix+'_patches_missed'] = count[total]-count[found]
        count[prefix+'_patch_miss_fraction'] = (count[total]-count[found])/count[total] if count[total] else None
    rusty_unique = [v for v in unique.values() if v['rusty']]
    clean_unique = [v for v in unique.values() if not v['rusty']]
    return dict(thresholds=dict(zip(('drum','corrosion','bulge'),thresholds)), counts=dict(count),
                unique_scene_drums=dict(total=len(unique), detected_in_any_view=sum(v['detected'] for v in unique.values()),
                    both_conditions_correct_in_at_least_one_view=sum(v['correct_any_view'] for v in unique.values()),
                    rusty=len(rusty_unique), rust_flagged_in_any_view=sum(v['rust_found_any_view'] for v in rusty_unique),
                    clean=len(clean_unique), clean_false_alert_in_any_view=sum(v['clean_false_alert_any_view'] for v in clean_unique)),
                rows=rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    args = parser.parse_args()
    thresholds=json.loads((args.run_dir/'thresholds.json').read_text())
    profiles = {'fixed_confidence_025':[.25]*3, 'fixed_confidence_050':[.5]*3,
                'validation_suspect':[thresholds[n]['suspect'] for n in ('drum','corrosion','bulge')],
                'validation_confirm':[thresholds[n]['confirm'] for n in ('drum','corrosion','bulge')]}
    report = dict(run_id=args.run_dir.name, split='test', images=150,
                  counting='Per-image visible barrel instances; repeated views also grouped separately by seed+drum ID.',
                  association='Predicted drum -> GT drum at IoU >= 0.5; rust via patch center/containment in predicted drum; bulge via box IoU >= 0.5. Approximate 2D associations, no identity labels in inference.',
                  correctness='Detected drum and correct visible-rust/bulge flags. Rust-enabled drums with no visible labeled rust are excluded from condition accuracy, not called clean.',
                  patch_matching='One-to-one confidence-ordered IoU >= 0.5. A patch with a loose box can count as missed even if rust presence was recognized.',
                  threshold_protocol='Two fixed conventional confidence levels plus already-frozen validation thresholds. No weights or thresholds selected using these test results.',
                  profiles={})
    for name,values in profiles.items():
        report['profiles'][name] = audit(args.dataset,args.run_dir/'evaluation/test/predictions.json','test',values)
    destination=args.run_dir/'evaluation/barrel_audit.json'
    destination.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:{'counts':v['counts'],'unique_scene_drums':v['unique_scene_drums']} for k,v in report['profiles'].items()},indent=2))


if __name__ == '__main__':
    main()
