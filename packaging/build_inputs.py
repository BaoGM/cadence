# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
from pathlib import Path
import subprocess

SOURCE = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_files():
    listing = SOURCE / 'packaging/source-files.txt'
    names = listing.read_text(encoding='utf-8').splitlines()
    if len(names) != len(set(names)):
        raise ValueError('Duplicate source entries')
    for name in names:
        path = SOURCE / name
        if not name or Path(name).anchor or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('Unsafe source entry')
        parents = [path, *path.parents[:len(Path(name).parts) - 1]]
        if any(p.is_symlink() or p.is_junction() for p in parents) or not path.is_file():
            raise ValueError(f'Missing or linked source: {name}')
    return {name: sha256(SOURCE / name) for name in sorted(names)}


def source_identity():
    files = source_files()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    commit = None
    if (SOURCE / '.git').exists():
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, capture_output=True, text=True)
        if result.returncode == 0:
            commit = result.stdout.strip()
    return {'source_sha256': digest, 'files': files, 'commit': commit}


def verify_tree(root, expected):
    root = Path(root).resolve()
    actual = {}
    for path in root.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise ValueError('Linked dependency input')
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = sha256(path)
    if actual != expected:
        bad = sorted(set(actual) ^ set(expected) | {k for k in actual.keys() & expected.keys() if actual[k] != expected[k]})
        raise ValueError(f'Input manifest mismatch: {bad[:12]}')
    return actual
