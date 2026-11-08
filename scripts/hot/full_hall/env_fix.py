# The cosmos_ai Modal secret stores the key as lower-case vllm_api_key; sensing.py reads VLLM_API_KEY.
import os as _env_os
if not _env_os.environ.get('VLLM_API_KEY') and _env_os.environ.get('vllm_api_key'):
    _env_os.environ['VLLM_API_KEY'] = _env_os.environ['vllm_api_key']
