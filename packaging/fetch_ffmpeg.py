# SPDX-License-Identifier: GPL-3.0-only
import hashlib
from pathlib import Path
import tempfile
import urllib.request
import zipfile

RELEASE='autobuild-2026-11-10-12-39'
NAME='ffmpeg-n9.0.2-48-gd4070a14ce-win64-gpl-9.0'
URL=f'https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/{RELEASE}/{NAME}.zip'
ARCHIVE_SHA256='e08cfa1d5ec52a4e405c55ddb6c91b42fb2a9dafe5bcecfcbffd6db3e9bdba0e'
EXECUTABLE_SHA256='13ff6c19ae468b95126489df1bed036d17ac2982be75cbdf998354b100520434'


def main():
    target=Path(__file__).resolve().parents[1]/'vendor'/'ffmpeg.exe'
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==EXECUTABLE_SHA256:
        print(target); return
    target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        archive=Path(folder)/'ffmpeg.zip'
        urllib.request.urlretrieve(URL,archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=ARCHIVE_SHA256:
            raise RuntimeError('FFmpeg archive checksum mismatch')
        with zipfile.ZipFile(archive) as source:
            data=source.read(f'{NAME}/bin/ffmpeg.exe')
        if hashlib.sha256(data).hexdigest()!=EXECUTABLE_SHA256:
            raise RuntimeError('FFmpeg executable checksum mismatch')
        temporary=target.with_suffix('.tmp'); temporary.write_bytes(data); temporary.replace(target)
    print(target)


if __name__=='__main__':
    main()
