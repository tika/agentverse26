"""Full Isaac Sim GUI in your browser: Isaac Sim -> Xvfb -> x11vnc -> noVNC -> Modal HTTPS tunnel.

Setup (once):
    modal secret create isaac-vnc VNC_PASSWORD=<something>   # the tunnel URL is public

Usage:
    modal run isaac_novnc.py::check     # do Modal containers get NVIDIA graphics libs + Vulkan?
    modal run isaac_novnc.py            # start the desktop, open the printed vnc.html link

Iteration loop:
    modal volume put isaac-work ./sim /sim --force   # push code (appears at /work/sim)
    sync                                             # in the remote xterm: reload the volume
    rec                                              # record the desktop to /work/recordings until Ctrl-C
    modal volume get isaac-work /recordings .        # download recordings

The GPU bills the whole time the desktop is up. Ctrl-C locally shuts it down.
"""

import base64
import os
import pathlib
import subprocess
import threading
import time

import modal

ISAAC_SIM_VERSION = "6.2.0"
# Isaac Sim needs RT cores: L40S, L4 or A10G work; A100/H100 do not. Override with ISAAC_GPU=L4.
GPU = os.environ.get("ISAAC_GPU", "L40S")

ISAAC_HOME = "/isaac-sim"
CACHE_DIR = "/cache"
WORK_DIR = "/work"
DISPLAY = ":1"
RESOLUTION = "1920x1080"
NOVNC_PORT = 6080

# Same cache layout as isaac_sim_modal.py, so the headless runner and the GUI share compiled shaders.
CACHE_LINKS = {
    f"{ISAAC_HOME}/.cache": f"{CACHE_DIR}/main",
    f"{ISAAC_HOME}/.nv/ComputeCache": f"{CACHE_DIR}/computecache",
    f"{ISAAC_HOME}/.nvidia-omniverse/logs": f"{CACHE_DIR}/logs",
    f"{ISAAC_HOME}/.local/share/ov/data": f"{CACHE_DIR}/data",
}

# The xterm talks to the Modal process through these flag files: Volume reload/commit
# are Python calls, so shell commands can't do them directly.
RELOAD_FLAG = "/tmp/volume-reload"
COMMIT_FLAG = "/tmp/volume-commit"

SYNC_SH = f"""#!/bin/bash
touch {RELOAD_FLAG}
while [ -e {RELOAD_FLAG} ]; do sleep 0.2; done
echo "volume reloaded: {WORK_DIR}/sim is up to date"
"""

REC_SH = f"""#!/bin/bash
mkdir -p {WORK_DIR}/recordings
out={WORK_DIR}/recordings/take-$(date +%Y%m%d-%H%M%S).mp4
echo "recording to $out (Ctrl-C to stop)"
ffmpeg -loglevel error -f x11grab -framerate 30 -video_size {RESOLUTION} -i {DISPLAY} \\
    -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p "$out"
touch {COMMIT_FLAG}
while [ -e {COMMIT_FLAG} ]; do sleep 0.2; done
echo "saved $out; download with: modal volume get isaac-work /recordings ."
"""

image = (
    modal.Image.from_registry(f"nvcr.io/nvidia/isaac-sim:{ISAAC_SIM_VERSION}", add_python="3.12")
    .entrypoint([])
    .apt_install("xvfb", "x11vnc", "novnc", "websockify", "openbox", "xterm", "ffmpeg", "vulkan-tools", "mesa-utils")
    .env(
        {
            "ACCEPT_EULA": "Y",
            "PRIVACY_CONSENT": "Y",
            "OMNI_KIT_ACCEPT_EULA": "YES",
            "HOME": ISAAC_HOME,
            "DISPLAY": DISPLAY,
            "NVIDIA_DRIVER_CAPABILITIES": "all",
        }
    )
    .run_commands(
        *(f"rm -rf {src} && mkdir -p $(dirname {src}) && ln -s {dst} {src}" for src, dst in CACHE_LINKS.items()),
        *(
            f"echo {base64.b64encode(body.encode()).decode()} | base64 -d > /usr/local/bin/{name} && chmod +x /usr/local/bin/{name}"
            for name, body in (("sync-work", SYNC_SH), ("rec", REC_SH))
        ),
        # `sync` is a coreutils command; alias it in interactive shells only.
        "echo 'alias sync=sync-work' >> /etc/bash.bashrc",
    )
    .add_local_dir(pathlib.Path(__file__).parent / "sim", remote_path="/sim-seed")
)

cache = modal.Volume.from_name("isaac-sim-cache", create_if_missing=True)
work = modal.Volume.from_name("isaac-work", create_if_missing=True)

app = modal.App("isaac-novnc", image=image)


@app.function(gpu=GPU, timeout=10 * 60)
def check():
    """Report whether the NVIDIA graphics (not just compute) driver libs are mounted."""
    libs = sorted(
        p.name
        for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib64")
        if pathlib.Path(d).is_dir()
        for p in pathlib.Path(d).iterdir()
        if p.name.startswith(("libGLX_nvidia", "libnvidia-glcore", "libnvidia-glvkspirv", "libEGL_nvidia"))
    )
    icds = [p for p in ("/etc/vulkan/icd.d/nvidia_icd.json", "/usr/share/vulkan/icd.d/nvidia_icd.json") if os.path.exists(p)]

    subprocess.run(["nvidia-smi"], check=False)
    print("graphics libs:", libs or "NONE")
    print("vulkan ICD files:", icds or "NONE")
    if not libs:
        print("\nNO NVIDIA GRAPHICS LIBS MOUNTED: Isaac Sim cannot render on this setup.")
        print("Ask Modal support to enable the graphics driver capability for your workspace.")
        return
    subprocess.run(["vulkaninfo", "--summary"], check=False, env={k: v for k, v in os.environ.items() if k != "DISPLAY"})
    print("\nPASS if an NVIDIA GPU is listed under 'Devices' above (not only llvmpipe).")


def _spawn(cmd: list[str], **kwargs) -> subprocess.Popen:
    return subprocess.Popen(cmd, **kwargs)


def _wait_for_x(timeout: float = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if subprocess.run(["xdpyinfo", "-display", DISPLAY], capture_output=True).returncode == 0:
            return
        if os.path.exists(f"/tmp/.X11-unix/X{DISPLAY[1:]}"):
            return
        time.sleep(0.5)
    raise RuntimeError("Xvfb did not come up")


def _watch_volume_flags(stop: threading.Event):
    while not stop.is_set():
        for flag, action in ((RELOAD_FLAG, work.reload), (COMMIT_FLAG, work.commit)):
            if os.path.exists(flag):
                try:
                    action()
                except Exception as e:  # reload fails while files on the volume are open
                    print(f"[novnc] {action.__name__} failed: {e}")
                os.remove(flag)
        stop.wait(0.5)


@app.function(
    gpu=GPU,
    cpu=8,
    memory=32 * 1024,
    timeout=6 * 60 * 60,
    volumes={CACHE_DIR: cache, WORK_DIR: work},
    secrets=[modal.Secret.from_name("isaac-vnc")],
)
def desktop():
    for dst in CACHE_LINKS.values():
        pathlib.Path(dst).mkdir(parents=True, exist_ok=True)
    sim_dir = pathlib.Path(WORK_DIR) / "sim"
    if not sim_dir.exists():
        subprocess.run(["cp", "-r", "/sim-seed", str(sim_dir)], check=True)

    subprocess.run(["x11vnc", "-storepasswd", os.environ["VNC_PASSWORD"], "/tmp/vncpass"], check=True, capture_output=True)

    procs = [_spawn(["Xvfb", DISPLAY, "-screen", "0", f"{RESOLUTION}x24", "-nolisten", "tcp"])]
    _wait_for_x()
    procs += [
        _spawn(["openbox"]),
        _spawn(["x11vnc", "-display", DISPLAY, "-rfbauth", "/tmp/vncpass", "-forever", "-shared", "-quiet", "-rfbport", "5900"]),
        _spawn(["websockify", "--web", "/usr/share/novnc", str(NOVNC_PORT), "localhost:5900"]),
        _spawn(["xterm", "-geometry", "120x30+0+0", "-e", "bash", "-i"], cwd=str(sim_dir)),
        _spawn([f"{ISAAC_HOME}/isaac-sim.sh", "--allow-root"], cwd=ISAAC_HOME),
    ]

    stop = threading.Event()
    watcher = threading.Thread(target=_watch_volume_flags, args=(stop,), daemon=True)
    watcher.start()

    with modal.forward(NOVNC_PORT) as tunnel:
        print(f"\nIsaac Sim desktop: {tunnel.url}/vnc.html?autoconnect=1&resize=scale\n")
        print("First launch compiles shaders for several minutes. Ctrl-C here to shut down.")
        try:
            while all(p.poll() is None for p in procs[:4]):
                time.sleep(5)
            print("[novnc] a desktop process exited; shutting down")
        finally:
            stop.set()
            for p in reversed(procs):
                p.terminate()
            cache.commit()
            work.commit()


@app.local_entrypoint()
def main():
    desktop.remote()
