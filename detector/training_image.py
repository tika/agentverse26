"""Pinned training/serving dependencies, entirely separate from Isaac Python."""
from pathlib import Path
import modal

ROOT=Path(__file__).resolve().parents[1]
image=(modal.Image.debian_slim(python_version='3.12')
       .apt_install('libgl1','libglib2.0-0','libgomp1')
       .pip_install('torch==2.9.1','torchvision==0.24.1',index_url='https://download.pytorch.org/whl/cu128')
       .pip_install('ultralytics==8.4.207','modal==1.6.3')
       .env({'OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','YOLO_AUTOINSTALL':'false',
             'YOLO_CONFIG_DIR':'/tmp/ultralytics','MPLCONFIGDIR':'/tmp/matplotlib',
             'NCCL_SHM_DISABLE':'1','TORCH_NCCL_ASYNC_ERROR_HANDLING':'1',
             'TORCH_NCCL_ENABLE_MONITORING':'1','TORCH_NCCL_HEARTBEAT_TIMEOUT_SEC':'180'}))
if modal.is_local():
    image=image.add_local_dir(ROOT/'detector','/workspace/detector',copy=True,
                              ignore=['__pycache__/**','**/*.pyc', 'serve_yolo26s.py',
                                      'api_client.py', 'training_status.py'])
