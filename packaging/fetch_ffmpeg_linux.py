# SPDX-License-Identifier: GPL-3.0-only
import hashlib
from pathlib import Path
import tarfile
import tempfile
import urllib.request

NAME = 'ffmpeg-n9.0.2-48-gd4070a14ce-linux64-gpl-9.0'
URL = f'https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-10-12-39/{NAME}.tar.xz'
ARCHIVE_SHA256 = '8206a48ce342b5075d0e0293e468a61198a55b3ef479bec3f7e83b04a18667d4'
EXECUTABLE_SHA256 = '65fe230487f353b4e1ff62d1dcfb61507380f72a8f10de8a38b97ed6e88ba928'


def main():
    target = Path(__file__).resolve().parents[1] / 'vendor/ffmpeg'
    target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        archive = Path(folder) / 'ffmpeg.tar.xz'
        urllib.request.urlretrieve(URL, archive)
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != ARCHIVE_SHA256:
                raise RuntimeError('FFmpeg archive checksum mismatch')
        with tarfile.open(archive) as source:
            entry = source.getmember(f'{NAME}/bin/ffmpeg')
            if not entry.isfile(): raise ValueError('Expected a regular FFmpeg executable')
            data = source.extractfile(entry).read()
        if hashlib.sha256(data).hexdigest() != EXECUTABLE_SHA256:
            raise RuntimeError('FFmpeg executable checksum mismatch')
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.chmod(0o755)
        temporary.replace(target)
    print(target)


if __name__ == '__main__':
    main()
