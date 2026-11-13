# SPDX-License-Identifier: GPL-3.0-only
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

if os.name == 'nt':
    from fetch_ffmpeg import EXECUTABLE_SHA256
else:
    from fetch_ffmpeg_linux import EXECUTABLE_SHA256


def generate(target):
    root = Path(__file__).resolve().parents[1]
    executable = root / 'vendor' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    with executable.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != EXECUTABLE_SHA256:
            raise ValueError('Unexpected FFmpeg binary')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(executable), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=960x540:rate=24:duration=8',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
        '-af', 'volume=2', '-ac', '2', '-c:v', 'libx264', '-preset', 'fast',
        '-crf', '10', '-g', '24', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
        '-b:a', '192k', '-movflags', '+faststart', str(target),
    ], check=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'assets/Demonstration.mp4')
    print(generate(parser.parse_args().output))
