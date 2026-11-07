"""Verify auth and real inference; provision private local client credentials once."""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from detector.api_client import predict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    from modal.workspace import Workspace
    credentials = ROOT/'.runtime/detector_api.env'
    credentials.parent.mkdir(exist_ok=True)
    if credentials.exists():
        values = {}
        for line in credentials.read_text().splitlines():
            name, value = line.removeprefix('export ').split('=', 1)
            values[name] = shlex.split(value)[0]
        key, secret = values['DETECTOR_API_KEY'], values['DETECTOR_API_SECRET']
    else:
        token = Workspace.from_context().proxy_tokens.create(name='agentverse-drum-detector-client')
        key, secret = token.token_id, token.token_secret
        # RBAC workspaces need an explicit environment association.
        import modal
        try:
            Workspace.from_context().proxy_tokens.allow(key, 'main')
        except modal.exception.InvalidError as error:
            if 'not environment-scoped' not in str(error):
                raise
    values = dict(DETECTOR_API_URL=args.url, DETECTOR_API_KEY=key, DETECTOR_API_SECRET=secret)
    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(''.join(f'export {name}={shlex.quote(value)}\n' for name, value in values.items()))
    os.chmod(credentials, 0o600)

    report = dict(url=args.url, run_id=args.run_id, image=str(args.image), credentials_file=str(credentials))
    try:
        urllib.request.urlopen(args.url+'/health', timeout=30)
        raise AssertionError('Unauthenticated request unexpectedly succeeded')
    except urllib.error.HTTPError as error:
        assert error.code in (401, 403), f'Unexpected unauthorized status {error.code}'
        report['unauthenticated_status'] = error.code
    request = urllib.request.Request(args.url+'/health', headers={'Modal-Key':key, 'Modal-Secret':secret})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=240) as response:
        health = json.loads(response.read())
    report['cold_health_seconds'] = time.perf_counter()-started
    assert health['run_id'] == args.run_id and health['status'] == 'ready'
    report['health'] = health
    started = time.perf_counter()
    result = predict(args.url, args.image, key, secret)
    report['warm_http_seconds'] = time.perf_counter()-started
    assert result['run_id'] == args.run_id and result['best_sha256'] == health['best_sha256']
    assert result['detections'] and all(r['class_name'] in ['drum', 'corrosion', 'bulge'] for r in result['detections'])
    assert result['operating_mode'] == 'fixed' and result['applied_thresholds'] == dict(drum=.25,corrosion=.25,bulge=.25)
    assert len(result['barrels']) == sum(r['class_id'] == 0 for r in result['detections'])
    report['prediction'] = result
    # Explicit override checks a separate request path without fitting to test data.
    malformed = urllib.request.Request(args.url+'/predict', data=b'not-an-image',
                                      headers={'Modal-Key':key, 'Modal-Secret':secret,
                                               'Content-Type':'application/octet-stream'})
    try:
        urllib.request.urlopen(malformed, timeout=30)
        raise AssertionError('Malformed request unexpectedly succeeded')
    except urllib.error.HTTPError as error:
        assert error.code == 422
        report['missing_file_status'] = error.code
    destination = ROOT/'out/detector_training'/args.run_id/'api_smoke.json'
    destination.write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(status='passed', url=args.url, run_id=args.run_id,
                          unauthorized_status=report['unauthenticated_status'],
                          detections=len(result['detections']), warm_http_seconds=report['warm_http_seconds'],
                          barrels=len(result['barrels']), gpu=health['gpu'],
                          model_speed_ms=result['model_speed_ms'], report=str(destination),
                          credentials_file=str(credentials)), indent=2))


if __name__ == '__main__':
    main()
