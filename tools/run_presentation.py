"""Render environment stills/flythrough on Modal, then encode a local MP4."""
from pathlib import Path
import subprocess
import imageio_ffmpeg
from run_hall import run_job,ROOT

if __name__=='__main__':
    run_job('presentation')
    directory=ROOT/'sim/out/presentation'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-framerate','10','-i',
                    str(directory/'video_frames/%05d.png'),'-c:v','libx264',
                    '-pix_fmt','yuv420p','-movflags','+faststart',
                    str(directory/'environment_walkthrough.mp4')],check=True)
    print('VIDEO_READY',directory/'environment_walkthrough.mp4')
