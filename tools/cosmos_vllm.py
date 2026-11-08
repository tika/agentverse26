"""Cosmos Reason 2 behind vLLM's OpenAI-compatible server on Modal.

    modal deploy tools/cosmos_vllm.py              # prints the endpoint URL
    python tools/cosmos_vllm.py smoke image.jpg    # one plate read from a laptop

One server handles every caller (plate reads, decisions, the report); vLLM batches concurrent requests.
Clients send `Authorization: Bearer $VLLM_API_KEY` from the `cosmos-vllm` Modal secret.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

import modal

MODEL = os.environ.get('CANIS_COSMOS_CHECKPOINT', 'nvidia/Cosmos-Reason2-2B')
SERVED_NAME = 'cosmos'
image = (modal.Image.debian_slim(python_version='3.12')
         .uv_pip_install('vllm==0.11.0', 'transformers==4.57.3', 'huggingface_hub[hf_transfer]')
         .env({'HF_HUB_ENABLE_HF_TRANSFER': '1'}))
app = modal.App('agentverse-cosmos-vllm')
hf_cache = modal.Volume.from_name('cosmos-hf-cache', create_if_missing=True)
vllm_cache = modal.Volume.from_name('cosmos-vllm-cache', create_if_missing=True)


@app.function(image=image, gpu='L40S', timeout=24 * 60 * 60, scaledown_window=20 * 60,
              volumes={'/root/.cache/huggingface': hf_cache, '/root/.cache/vllm': vllm_cache},
              secrets=[modal.Secret.from_name('huggingface', required_keys=['HF_TOKEN']),
                       modal.Secret.from_name('cosmos-vllm', required_keys=['VLLM_API_KEY'])])
@modal.concurrent(max_inputs=16)
@modal.web_server(port=8000, startup_timeout=20 * 60)
def serve():
    subprocess.Popen(['vllm', 'serve', MODEL, '--served-model-name', SERVED_NAME, '--host', '0.0.0.0',
                      '--port', '8000', '--api-key', os.environ['VLLM_API_KEY'], '--max-model-len', '16384',
                      '--gpu-memory-utilization', '0.85', '--limit-mm-per-prompt', '{"image": 2, "video": 0}'])


def chat(url, key, messages, max_tokens=512, timeout=300):
    body = json.dumps({'model': SERVED_NAME, 'messages': messages, 'max_tokens': max_tokens,
                       'temperature': 0.0}).encode()
    request = urllib.request.Request(url.rstrip('/') + '/v1/chat/completions', data=body, method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())['choices'][0]['message']['content']


if __name__ == '__main__' and sys.argv[1:2] == ['smoke']:
    url = modal.Function.from_name('agentverse-cosmos-vllm', 'serve').get_web_url()
    key = os.environ['VLLM_API_KEY']
    jpeg = base64.b64encode(Path(sys.argv[2]).read_bytes()).decode()
    print(url)
    print(chat(url, key, [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{jpeg}'}},
        {'type': 'text', 'text': 'Read the waste drum plate (category and ID). Answer with only JSON: '
                                 '{"drum_id": ..., "category": ...}.'}]}]))
