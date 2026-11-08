# Using Cosmos Reason 2 8B

The team's Cosmos model is `nvidia/Cosmos-Reason2-8B`, served by vLLM on Modal
(`tools/cosmos_vllm.py`). It replaced the 2B model. The API is OpenAI-compatible,
so any OpenAI client or plain HTTP works. It accepts text and up to 2 images per
request (no video).

| Setting | Value |
| --- | --- |
| Base URL | `https://levi-stein-26--agentverse-cosmos-vllm-serve.us-east.modal.run` |
| Chat endpoint | `<base URL>/v1/chat/completions` |
| Model name | `cosmos` |
| Auth header | `Authorization: Bearer <key>` |
| Context length | 16,384 tokens (prompt + answer) |

**The key is not in Git.** Ask Levi for it and keep it out of code, commits,
logs, videos and screenshots. Anyone holding it can run requests on Levi's GPU.

## 1. Store the key locally

Create `.runtime/cosmos.env` (already ignored by Git) and make it private:

```dotenv
COSMOS_URL=https://levi-stein-26--agentverse-cosmos-vllm-serve.us-east.modal.run
COSMOS_MODEL=cosmos
VLLM_API_KEY=<key from Levi>
```

```sh
chmod 600 .runtime/cosmos.env
```

Use the base URL **without** `/v1`; the repo's callers append `/v1/chat/completions`.

## 2. Check that it works

```sh
set -a; source .runtime/cosmos.env; set +a
curl -s "$COSMOS_URL/v1/models" -H "Authorization: Bearer $VLLM_API_KEY"
```

You should see `"root":"nvidia/Cosmos-Reason2-8B"`. A `401` means the key is wrong.

**Cold start:** the server shuts down after 20 minutes without requests. The
next request waits a few minutes while the model loads, so use a long client
timeout (180–300 s) for the first call. Later calls take seconds.

## 3. Use it from the repo's existing processes

Nothing in the code needs changing. The model name is still `cosmos`; only the
URL and key are new.

**Hot hall worker (simulation agent, sensing, reports).** Push the settings
into the running worker:

```sh
python3 tools/hot_hall.py cosmos-config .runtime/cosmos.env
```

This saves the settings in a private Modal Dict. `scripts/hot/sensing.py`
(`cosmos_chat`) reads them before each request. If you skip this step, the
worker uses the `agentverse-cosmos-vllm` deployment in the Modal workspace it
runs in. In that case it also needs `VLLM_API_KEY` set.

**Static hall review.** `tools/review_hall_with_cosmos.py` reads
`.runtime/cosmos.env` directly:

```sh
python3 tools/review_hall_with_cosmos.py
```

**Plate-read smoke test.**

```sh
set -a; source .runtime/cosmos.env; set +a
uvx --with modal python tools/cosmos_vllm.py smoke path/to/plate.jpg
```

This test looks up the endpoint by Modal app name, so it only works when your
Modal CLI is logged in to the `levi-stein-26` workspace. Everywhere else, use
the URL above.

## 4. Use it from your own code

### Python (`openai` package)

```python
import base64, os
from openai import OpenAI

client = OpenAI(base_url=os.environ['COSMOS_URL'] + '/v1',
                api_key=os.environ['VLLM_API_KEY'], timeout=300)

jpeg = base64.b64encode(open('frame.jpg', 'rb').read()).decode()
reply = client.chat.completions.create(
    model='cosmos',
    temperature=0,
    max_tokens=512,
    messages=[{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{jpeg}'}},
        {'type': 'text', 'text': 'Read the waste drum plate. Answer with only JSON: '
                                 '{"drum_id": ..., "category": ...}'},
    ]}],
)
print(reply.choices[0].message.content)
```

### Python (standard library only)

Use the pattern in `tools/cosmos_vllm.py` (`chat`) or `scripts/hot/sensing.py`
(`cosmos_chat`): POST JSON to `<base>/v1/chat/completions` with the bearer header.

### curl

```sh
curl -s "$COSMOS_URL/v1/chat/completions" \
  -H "Authorization: Bearer $VLLM_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"cosmos","temperature":0,"max_tokens":200,
       "messages":[{"role":"user","content":"What should a robot do if it sees a spill in an aisle?"}]}'
```

### Structured JSON output

When a process needs machine-readable decisions, send a JSON schema. vLLM then
forces the answer to match it (see `tools/review_hall_with_cosmos.py`):

```python
schema = {'type': 'object', 'additionalProperties': False,
          'required': ['next_action', 'reason'],
          'properties': {
              'next_action': {'type': 'string',
                              'enum': ['inspect_closer', 'take_second_view', 'continue_patrol']},
              'reason': {'type': 'string', 'maxLength': 200}}}

reply = client.chat.completions.create(
    model='cosmos', temperature=0, max_tokens=300, messages=messages,
    response_format={'type': 'json_schema',
                     'json_schema': {'name': 'decision', 'schema': schema, 'strict': True}})
```

## Tips

- **Use a schema for anything a program parses.** If you only ask for JSON in
  the prompt, the model wraps it in a ```` ```json ```` code block and may
  put values in the wrong fields. A `response_format` schema returns clean
  JSON in the exact shape.
- **Images:** send JPEGs as base64 data URLs. At most 2 per request. Downscale
  to about 640–1024 px on the long side; it is faster and works as well.
- **Determinism:** pass `temperature: 0`. Otherwise the model uses its default
  sampling (0.7).
- **Concurrency:** one server takes up to 16 requests at once and runs them
  together, so parallel callers are fine.
- **Errors:** `401` means a bad key. A timeout on the first call is usually the
  cold start, so retry with a longer timeout. Treat a failed call as "no answer";
  never fall back to simulated ground truth.
- **LoRA adapters:** adapters trained on the 2B model (`tools/train_spot_lora.py`)
  do not load on 8B.

## Owner operations (Levi)

```sh
modal deploy tools/cosmos_vllm.py                      # redeploy after changes
modal app stop agentverse-cosmos-vllm                  # take it offline
modal secret create cosmos-vllm VLLM_API_KEY=<new> --force && modal deploy tools/cosmos_vllm.py   # rotate the key
```

After rotating the key, send teammates the new key. Their `.runtime/cosmos.env`
and `hot_hall.py cosmos-config` need updating.
