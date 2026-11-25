# SPDX-License-Identifier: GPL-3.0-only
import hashlib
from pathlib import Path
import tempfile
import urllib.request
import zipfile

RELEASE='autobuild-2026-11-24-12-41'
NAME='ffmpeg-n9.0.2-963-g4d831360c9-win64-gpl-9.0'
URL=f'https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/{RELEASE}/{NAME}.zip'
ARCHIVE_SHA256='378bb3b24dcbefe9ecd07f54bd5a4787701890ec10d47cc10b8c02d39d799eef'
EXECUTABLE_SHA256='cc4737d115fd010b193d1acf0c9ccc3eb3a6f7a8e12716c305cdd3d83e9111f2'


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
