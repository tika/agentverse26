# Confirms the worker reaches the latest detector and that it is exactly the published model. Never records credentials.
def _yolo_ping():
    import json, os, urllib.request
    expected = {'comparison_id': 'compare_colors_20261108T053740Z_continued',
                'best_sha256': 'ba4c80bcb99f6152d8ee0a6523151c4640ad67d727431b9ec846235dcf895b6a'}
    result = {}
    try:
        request = urllib.request.Request(os.environ['DETECTOR_API_URL'].rstrip('/') + '/health',
                                         headers={'Modal-Key': os.environ['DETECTOR_API_KEY'], 'Modal-Secret': os.environ['DETECTOR_API_SECRET']})
        with urllib.request.urlopen(request, timeout=240) as response:
            health = json.load(response)
        result.update({k: health.get(k) for k in ('status', 'comparison_id', 'dataset_id', 'best_sha256', 'label_schema', 'classes')})
        result['ok'] = all(health.get(k) == v for k, v in expected.items())
    except Exception as error:
        result.update(ok=False, error=repr(error)[-160:])
    (OUT / 'yolo_ping.json').write_text(json.dumps(result))


_yolo_ping()
del _yolo_ping
