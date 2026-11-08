"""Check everything the hot worker depends on before spending a GPU. Exit code 1 on any failure.

    uv run --python 3.13 --with modal --with numpy --with pillow python tools/preflight.py   # before `up` and before a mission

Then `hot_hall.py run scripts/hot/sensing.py scripts/hot/scenario_lib.py scripts/hot/yolo.py
scripts/hot/agent.py scripts/hot/smoke_e2e.py` checks the same services from inside the worker.
"""
import ast
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import urllib.request

import modal

ROOT = Path(__file__).resolve().parents[1]
results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail or ''))
    except Exception as error:  # Every failure is reported, none stops the others.
        results.append((False, name, f'{type(error).__name__}: {error}'[:300]))


def env_file(path):
    values = {}
    for line in (ROOT / path).read_text().splitlines():
        line = line.strip().removeprefix('export ')
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')
    return values


def http(url, headers=None, timeout=300):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def compiles():
    files = [*sorted((ROOT / 'scripts/hot').glob('*.py')), ROOT / 'sim/hot_server.py', ROOT / 'tools/hot_hall.py']
    for path in files:
        py_compile.compile(str(path), doraise=True)
    return f'{len(files)} files'


def deterministic_modal_definitions():
    """Modal re-evaluates decorators inside the container: they must not depend on local env or conditionals."""
    tree = ast.parse((ROOT / 'tools/hot_hall.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.IfExp) or (isinstance(sub, ast.Attribute) and sub.attr == 'environ'):
                        raise AssertionError(f'{node.name}: decorator depends on a condition or os.environ '
                                             f'(line {sub.lineno}); the container would see a different definition')
    return 'no conditional or env-dependent decorator arguments'


def secrets_exist():
    names = ['cosmos-vllm', 'drum-inference', 'huggingface']
    for name in names:
        modal.Secret.from_name(name).hydrate()
    return ', '.join(names)


def cosmos_service():
    url = modal.Function.from_name('agentverse-cosmos-vllm', 'serve').get_web_url().rstrip('/')
    status, _ = http(url + '/health')
    assert status == 200, f'/health returned {status}'
    key = env_file('.runtime/cosmos.env').get('VLLM_API_KEY')
    if not key:
        return f'{url} healthy; auth NOT checked (no .runtime/cosmos.env)'
    status, body = http(url + '/v1/models', {'Authorization': f'Bearer {key}'})
    assert status == 200, f'/v1/models with key returned {status}: the worker secret may hold a stale key'
    return f'healthy, key accepted, model {json.loads(body)["data"][0]["id"]}'


def detector_service():
    env = env_file('.runtime/detector_api.env')
    status, body = http(env['DETECTOR_API_URL'].rstrip('/') + '/health',
                        {'Modal-Key': env['DETECTOR_API_KEY'], 'Modal-Secret': env['DETECTOR_API_SECRET']})
    assert status == 200, f'/health returned {status}'
    health = json.loads(body)
    return f"{health['status']}, {health['model']} run {health['run_id']}"


def unit_tests():
    run = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'sim/tests'], cwd=ROOT,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-400:]
    return run.stderr.strip().splitlines()[-1]


def single_worker():
    apps = json.loads(subprocess.run(['modal', 'app', 'list', '--json'], capture_output=True, text=True).stdout)
    field = lambda a, *names: next((a[n] for n in names if n in a), None)  # Field names differ across CLI versions.
    running = [a for a in apps if field(a, 'Description', 'Name', 'name', 'description') == 'agentverse-hot-hall'
               and not field(a, 'Stopped at', 'stopped_at') and str(field(a, 'Tasks', 'tasks', 'n_running_tasks')) != '0']
    assert len(running) <= 1, f"{len(running)} hot workers running " \
                              f"({', '.join(str(field(a, 'App ID', 'app_id')) for a in running)}): " \
                              f'they share one request queue'
    return f'{len(running)} running'


check('code compiles', compiles)
check('Modal definitions deterministic', deterministic_modal_definitions)
check('secrets exist', secrets_exist)
check('Cosmos vLLM service', cosmos_service)
check('YOLO detector API', detector_service)
check('sim unit tests', unit_tests)
check('at most one hot worker', single_worker)
width = max(len(name) for _, name, _ in results)
for ok, name, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
sys.exit(0 if all(ok for ok, _, _ in results) else 1)
