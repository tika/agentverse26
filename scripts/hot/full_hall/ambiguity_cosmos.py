"""Load after rigid_recording_setup and before rigid_middle_upper."""
import base64
import hashlib
import io
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


def make_rigid_ambiguity_planner():
    config_path = os.environ.get('COSMOS_CONFIG_FILE')
    config = json.loads(Path(config_path).read_text()) if config_path else {}
    endpoint = config.get('COSMOS_URL') or os.environ['COSMOS_URL']
    key = config.get('VLLM_API_KEY') or os.environ['VLLM_API_KEY']
    alias = config.get('COSMOS_MODEL', 'cosmos')
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}

    with urlopen(Request(endpoint.rstrip('/') + '/v1/models', headers=headers), timeout=300) as response:
        models = json.load(response)['data']
    root = next((model.get('root') for model in models if model['id'] == alias), None)
    if root != 'nvidia/Cosmos-Reason2-8B':
        raise RuntimeError('Expected the Cosmos Reason 2 8B endpoint from PR #3')
    print(f'[hot] Verified planner: {root}', flush=True)

    def choose(rgb, observation):
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format='PNG')
        image_bytes = buffer.getvalue()
        image_url = 'data:image/png;base64,' + base64.b64encode(image_bytes).decode()
        actions = observation.get('offered_actions', ['recheck_higher', 'defer_for_operator'])
        schema = {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': actions}},
                  'required': ['action'], 'additionalProperties': False}
        instruction = (
            'The goal is usable visual evidence for this drum. The observation gives the original plan. '
            'Use the target and surrounding barrel evidence together. Neighbor predictions are provisional. '
            'Use only the supplied observations and treat unsampled sensor channels as unknown. '
            'A higher body pitch is available for one extra view of the same target. '
            'When recheck_xy is offered, it moves to a second ground position and aims at the same barrel. '
            'Choose it when an anomalous apparent surface reading warrants checking from another viewpoint. '
            'Choose continue_inspection when offered and the first look provides sufficient evidence. Choose recheck_higher if it could resolve incomplete framing or uncertain visual evidence. '
            'Choose defer_for_operator if another view would not help. '
            'A partial view cannot clear the drum. Return only the action as JSON.'
        )
        payload = {'model': alias, 'temperature': 0, 'max_tokens': 512,
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'inspection_action', 'strict': True, 'schema': schema}},
                   'messages': [{'role': 'user', 'content': [
                       {'type': 'text', 'text': instruction + '\nObservation: ' + json.dumps(observation)},
                       {'type': 'image_url', 'image_url': {'url': image_url}}]}]}
        request = Request(endpoint.rstrip('/') + '/v1/chat/completions',
                          data=json.dumps(payload).encode(), headers=headers)
        started = time.perf_counter()
        with urlopen(request, timeout=300) as response:
            result = json.load(response)
        action = json.loads(result['choices'][0]['message']['content'])['action']
        if action not in actions:
            raise ValueError('Cosmos selected an action outside the offered set')
        return {'decision': action, 'source': root, 'offered_actions': actions,
                'request_wall_s': round(time.perf_counter() - started, 3),
                'input_sha256': hashlib.sha256(image_bytes).hexdigest(),
                'response_id': result.get('id')}

    choose.model = root
    return choose


rigid_ambiguity_planner = make_rigid_ambiguity_planner()
