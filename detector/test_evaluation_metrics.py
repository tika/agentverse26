import unittest
from detector.evaluation_metrics import at_threshold, calibrate, fixed_metrics, match_detections


class MetricsTests(unittest.TestCase):
    def test_duplicate_and_wrong_image_are_false_positives(self):
        truth = [dict(image_id='a', class_id=1, box=[0, 0, 10, 10])]
        preds = [dict(image_id=name, class_id=1, box=[0, 0, 10, 10], confidence=score)
                 for name, score in [('a', .9), ('a', .8), ('b', .7)]]
        matches, total = match_detections(truth, preds, 1)
        report = at_threshold(matches, total, .5, 2)
        self.assertEqual((report['tp'], report['fp'], report['fn']), (1, 2, 0))
        self.assertAlmostEqual(report['precision'], 1/3)

    def test_frozen_threshold_is_applied_to_unseen_false_positives(self):
        truth = [dict(image_id='a', class_id=c, box=[0, 0, 10, 10]) for c in range(3)]
        preds = [dict(row, confidence=.8) for row in truth]
        thresholds = calibrate(truth, preds, 1)
        extra = [dict(image_id='b', class_id=1, box=[0, 0, 10, 10], confidence=.99)]
        metrics = fixed_metrics(truth, preds+extra, 2, thresholds)
        self.assertEqual(metrics['corrosion']['suspect']['fp'], 1)
        self.assertFalse(thresholds['corrosion']['precision_target_met'])  # fewer than 5 examples


if __name__ == '__main__':
    unittest.main()
