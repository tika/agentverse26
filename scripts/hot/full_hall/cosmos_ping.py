# One small text request, to wake the Cosmos service and prove it answers before spending a render. Never records the key.
# Everything is inside a function because worker scripts share one namespace.
def _cosmos_ping():
    import json, os, pathlib, time, urllib.request
    url, key, model = os.environ.get('COSMOS_URL'), os.environ.get('VLLM_API_KEY'), os.environ.get('COSMOS_MODEL', 'cosmos')
    path = os.environ.get('COSMOS_CONFIG_FILE')
    if path and pathlib.Path(path).exists():
        cfg = json.loads(pathlib.Path(path).read_text())
        url, key, model = cfg.get('COSMOS_URL', url), cfg.get('VLLM_API_KEY', key), cfg.get('COSMOS_MODEL', model)
    result, started = {'has_url': bool(url), 'has_key': bool(key)}, time.perf_counter()
    try:
        body = json.dumps({'model': model, 'max_tokens': 40, 'temperature': 0.0,
                           'messages': [{'role': 'user', 'content': 'Reply with only the JSON {"ok": true}.'}]}).encode()
        request = urllib.request.Request(url.rstrip('/') + '/v1/chat/completions', data=body, method='POST',
                                         headers={'Content-Type': 'application/json', **({'Authorization': f'Bearer {key}'} if key else {})})
        with urllib.request.urlopen(request, timeout=420) as response:
            result['answer'] = json.loads(response.read())['choices'][0]['message']['content'][-120:]
        result['ok'] = True
    except Exception as error:
        result.update(ok=False, error=repr(error)[-160:])
    result['latency_s'] = round(time.perf_counter() - started, 1)
    (OUT / 'cosmos_ping.json').write_text(json.dumps(result))


_cosmos_ping()
del _cosmos_ping
