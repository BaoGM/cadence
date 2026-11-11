# SPDX-License-Identifier: GPL-3.0-only
import argparse
import json
from pathlib import Path
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile

from build_inputs import SOURCE, sha256, verify_tree


def extract(archive, destination, expected):
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError('Dependency archive must match the committed file manifest')
        if sum(item.file_size for item in entries) > 2_000_000_000:
            raise ValueError('Unexpected dependency bundle size')
        for item in entries:
            path = Path(item.filename)
            if path.anchor or '..' in path.parts or ':' in item.filename or '\\' in item.filename:
                raise ValueError('Unsafe archive path')
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Archive symlinks are forbidden')
            output = destination / path
            output.parent.mkdir(parents=True, exist_ok=True)
            with source.open(item) as src, output.open('xb') as dst:
                while block := src.read(1024 * 1024):
                    dst.write(block)
            if sha256(output) != expected[item.filename]:
                raise ValueError(f'Dependency checksum mismatch: {item.filename}')
    verify_tree(destination, expected)


def main():
    parser = argparse.ArgumentParser()
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--archive', type=Path)
    origin.add_argument('--url')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, default=SOURCE / '.deps/release-inputs')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Choose a new directory for dependency extraction')
    lock = json.loads((SOURCE / 'packaging/third-party.lock.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as temp:
        archive = args.archive
        if args.url:
            parsed = urllib.parse.urlsplit(args.url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('An HTTPS URL without embedded credentials is required')
            archive = Path(temp) / 'inputs.zip'
            with urllib.request.urlopen(args.url, timeout=60) as response, archive.open('wb') as output:
                count = 0
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > 2_000_000_000:
                        raise ValueError('Download exceeds dependency bundle size limit')
                    output.write(block)
        if sha256(archive) != args.sha256.lower():
            raise ValueError('Dependency bundle SHA-256 mismatch')
        extract(archive, args.output, lock['files'])
    print('Dependency source and notice bundle verified.')


if __name__ == '__main__':
    main()
