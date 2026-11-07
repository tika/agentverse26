"""Run the bounded Stage 1 RTX PRO 6000 benchmark and return compact evidence."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

import modal
ROOT = Path(__file__).resolve().parent
image = (modal.Image.from_registry('nvcr.io/nvidia/isaac-sim:6.2.0', add_python='3.13',
                                 setup_dockerfile_commands=['USER root'])
         .entrypoint([])
         .env({'ACCEPT_EULA':'Y','PRIVACY_CONSENT':'N','NVIDIA_DRIVER_CAPABILITIES':'all'})
         .pip_install('imageio-ffmpeg')
         .add_local_dir(ROOT/'sim', '/scene', copy=True, ignore=['out/**','__pycache__/**'])
         .add_local_dir(ROOT/'scripts', '/scripts', copy=True))

app = modal.App("agentverse-stage2-rtx", image=image)


@app.function(gpu="RTX-PRO-6000",
              cpu=8, memory=32768, timeout=900, max_containers=1,
              scaledown_window=5)
def benchmark():
    import imageio_ffmpeg


    root = Path("/tmp/stage2")
    root.mkdir()
    hardware = subprocess.check_output([
        "nvidia-smi", "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader",
    ], text=True).strip()
    print(hardware, flush=True)
    assert "RTX PRO 6000" in hardware
    version = Path("/isaac-sim/VERSION").read_text().strip()
    assert version.startswith("6.2.0"), version
    log = root / "isaac.log"
    started = time.perf_counter()
    with log.open("w") as stream:
        result = subprocess.run([
            "/isaac-sim/python.sh", "/scripts/spot_spill.py", "--radiation",
        ], env={**os.environ, "OUTPUT_DIR": str(root)},
            stdout=stream, stderr=subprocess.STDOUT, timeout=700, cwd="/isaac-sim")
    elapsed = time.perf_counter() - started
    timing_path = root / "spot-radiation" / "timing.json"
    if result.returncode == 0 and timing_path.exists():
        timing = json.loads(timing_path.read_text())
        run = timing["radiation"]
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        frames = next(root.rglob("00000.jpg")).parent
        subprocess.run([
            ffmpeg, "-loglevel", "error", "-framerate", str(run["frames"] / run["simulated_s"]),
            "-i", str(frames / "%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(root / "stage1-review.mp4"),
        ], check=True, timeout=60)
    (root / "hardware.json").write_text(json.dumps({
        "gpu": hardware, "isaac_version": version, "subprocess_wall_s": elapsed,
        "returncode": result.returncode,
    }, indent=2))
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for path in root.rglob("*"):
            if path.is_file() and (path.suffix != ".jpg" or path.name in {"00000.jpg", "00040.jpg", "00080.jpg"}):
                archive.add(path, arcname=path.relative_to(root))
    return payload.getvalue()


@app.local_entrypoint()
def main(output: str):
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(benchmark.remote())) as archive:
        archive.extractall(destination, filter="data")
    if not (destination / "stage1-review.mp4").is_file():
        raise RuntimeError(f"Isaac capture did not produce a video. Inspect {destination / 'isaac.log'}")
    print(destination)
