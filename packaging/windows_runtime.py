# SPDX-License-Identifier: GPL-3.0-only
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor/windows-runtime'
MANIFEST = Path(__file__).with_name('windows-runtime.json')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def substitute_runtime(binaries):
    expected = json.loads(MANIFEST.read_text(encoding='utf-8'))['files']
    found = set()
    result = []
    for dest, original, kind in binaries:
        name = Path(dest).as_posix()
        if name in expected:
            entry = expected[name]
            source = VENDOR / name if entry['component'] == 'OpenSSL' else Path(original)
            if not source.is_file() or sha256(source) != entry['sha256']:
                raise RuntimeError(f'Windows runtime input missing or incompatible: {name}')
            original = str(source)
            found.add(name)
        result.append((dest, original, kind))
    missing = sorted(expected.keys() - found)
    if missing:
        raise RuntimeError(f'Missing Windows runtime entries: {missing}')
    return result


def prepare_tls(folder):
    files = json.loads(MANIFEST.read_text(encoding='utf-8'))['files']
    VENDOR.mkdir(parents=True, exist_ok=True)
    for name, entry in files.items():
        if entry['component'] != 'OpenSSL':
            continue
        source = folder / name
        target = VENDOR / name
        if sha256(source) != entry['sha256']:
            raise ValueError(f'OpenSSL input checksum mismatch: {name}')
        if target.is_file() and sha256(target) == entry['sha256']:
            continue
        with tempfile.TemporaryDirectory(dir=VENDOR) as temporary:
            copy = Path(temporary) / name
            shutil.copyfile(source, copy)
            copy.replace(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tls', type=Path, required=True)
    prepare_tls(parser.parse_args().tls)
