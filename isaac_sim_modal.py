"""Run NVIDIA Isaac Sim headless on Modal.

Usage:
    modal run isaac_sim_modal.py                                  # smoke test, writes out/smoke.png
    modal run isaac_sim_modal.py --script scripts/my_sim.py      # run any standalone script
    modal shell isaac_sim_modal.py::shell                        # interactive shell in the container

Standalone scripts run under Isaac Sim's bundled Python (/isaac-sim/python.sh), so they can
`from isaacsim import SimulationApp`. Anything a script writes to $OUTPUT_DIR is returned and
saved locally under ./out/.
"""

import io
import os
import pathlib
import subprocess
import tarfile
import time

import modal

ISAAC_SIM_VERSION = "6.2.0"
# Isaac Sim needs RT cores: L40S, L4 or A10G work; A100/H100 do not. Override with ISAAC_GPU=L4.
GPU = os.environ.get("ISAAC_GPU", "L40S")

ISAAC_HOME = "/isaac-sim"
CACHE_DIR = "/cache"
OUTPUT_DIR = "/tmp/isaac-out"

# Isaac Sim's per-user caches (shaders, compute kernels, extensions). Persisting them in a
# Volume turns the multi-minute first-run shader compile into a one-time cost.
CACHE_LINKS = {
    f"{ISAAC_HOME}/.cache": f"{CACHE_DIR}/main",
    f"{ISAAC_HOME}/.nv/ComputeCache": f"{CACHE_DIR}/computecache",
    f"{ISAAC_HOME}/.nvidia-omniverse/logs": f"{CACHE_DIR}/logs",
    f"{ISAAC_HOME}/.local/share/ov/data": f"{CACHE_DIR}/data",
}

base_image = (
    modal.Image.from_registry(f"nvcr.io/nvidia/isaac-sim:{ISAAC_SIM_VERSION}", add_python="3.12")
    .entrypoint([])  # the image defaults to runheadless.sh; Modal needs to own the entrypoint
    .env(
        {
            "ACCEPT_EULA": "Y",
            "PRIVACY_CONSENT": "Y",
            "OMNI_KIT_ACCEPT_EULA": "YES",
            "HOME": ISAAC_HOME,
            "OUTPUT_DIR": OUTPUT_DIR,
        }
    )
    .run_commands(
        *(f"rm -rf {src} && mkdir -p $(dirname {src}) && ln -s {dst} {src}" for src, dst in CACHE_LINKS.items())
    )
)


def mount_scene(runtime_image):
    return runtime_image.add_local_dir(pathlib.Path(__file__).parent / "scripts", remote_path="/scripts").add_local_dir(
        pathlib.Path(__file__).parent / "sim", remote_path="/scene",
        ignore=["out/**", "__pycache__/**"],
    )


image = mount_scene(base_image)

cache = modal.Volume.from_name("isaac-sim-cache", create_if_missing=True)

app = modal.App("isaac-sim", image=image)


def _prepare_cache():
    for dst in CACHE_LINKS.values():
        pathlib.Path(dst).mkdir(parents=True, exist_ok=True)
    pathlib.Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


@app.function(gpu=GPU, volumes={CACHE_DIR: cache}, timeout=60 * 60, cpu=8, memory=32 * 1024)
def run(script_name: str, script_source: str | None = None, args: list[str] | None = None) -> bytes:
    """Run a standalone Isaac Sim script and return $OUTPUT_DIR as a tar.gz."""
    _prepare_cache()
    if script_source is not None:
        path = pathlib.Path("/tmp") / script_name
        path.write_text(script_source)
    else:
        path = pathlib.Path("/scripts") / script_name

    started = time.perf_counter()
    try:
        subprocess.run([f"{ISAAC_HOME}/python.sh", str(path), *(args or [])], check=True, cwd=ISAAC_HOME)
    finally:
        exited = time.perf_counter()
        cache.commit()
        print(f"[timing] Isaac subprocess {exited - started:.2f}s; cache commit {time.perf_counter() - exited:.2f}s", flush=True)

    started = time.perf_counter()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(OUTPUT_DIR, arcname=".")
    print(f"[timing] archive {time.perf_counter() - started:.2f}s; {buf.tell()} bytes", flush=True)
    return buf.getvalue()


@app.function(
    gpu=GPU,
    volumes={
        CACHE_DIR: cache,
        "/spot-takes": modal.Volume.from_name("isaac-spot-takes", create_if_missing=True),
    },
    timeout=24 * 60 * 60,
    cpu=8,
    memory=32 * 1024,
)
def warm():
    """Keep the Spot video scene and renderer loaded between takes."""
    _prepare_cache()
    subprocess.run(
        [f"{ISAAC_HOME}/python.sh", "/scripts/spot_walk_video.py", "--warm"],
        cwd=ISAAC_HOME,
        env={**os.environ, "OUTPUT_DIR": "/spot-takes"},
        check=True,
    )


@app.function(gpu=GPU, volumes={CACHE_DIR: cache}, timeout=60 * 60)
def shell():
    """Placeholder target for `modal shell isaac_sim_modal.py::shell`."""


@app.local_entrypoint()
def main(script: str = "", args: str = "", output: str = "out"):
    started = time.perf_counter()
    if script:
        local = pathlib.Path(script)
        payload = run.remote(local.name, local.read_text(), args.split())
    else:
        payload = run.remote("smoke_test.py")

    returned = time.perf_counter()
    out = pathlib.Path(output)
    out.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        tar.extractall(out)  # archive comes from our own container
    print(f"[timing] remote call plus transfer {returned - started:.2f}s; local extraction {time.perf_counter() - returned:.2f}s")
    print(f"Outputs saved to {out.resolve()}: {sorted(p.name for p in out.iterdir())}")
