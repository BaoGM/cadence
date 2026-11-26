# SPDX-License-Identifier: GPL-3.0-only
"""Prepare the pinned optional RIFE 4.6 runtime for the Windows build."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

from build_inputs import SOURCE, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--redist', type=Path, required=True, help='x64 Microsoft.VC143.OpenMP/vcomp140.dll from the matching MSVC redist')
    parser.add_argument('--archive', type=Path, help='Verified upstream RIFE Windows ZIP (downloaded if omitted)')
    parser.add_argument('--output', type=Path, default=SOURCE / '.deps/rife')
    args = parser.parse_args()
    spec = json.loads((SOURCE / 'packaging/rife-runtime.json').read_text('utf-8'))
    dest = args.output.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if sha256(args.redist) != spec['files']['vcomp140.dll']:
        raise ValueError('Unexpected x64 Microsoft OpenMP runtime')
    with tempfile.TemporaryDirectory(dir=dest) as working:
        stage = Path(working)
        archive = args.archive
        if archive is None:
            archive = stage / 'upstream.zip'
            with urllib.request.urlopen(spec['archive'], timeout=120) as src, archive.open('wb') as out:
                shutil.copyfileobj(src, out)
        if sha256(archive) != spec['archive_sha256']:
            raise ValueError('Unexpected RIFE upstream archive')
        with zipfile.ZipFile(archive) as upstream:
            for name, expected in spec['files'].items():
                out = stage / name
                out.parent.mkdir(parents=True, exist_ok=True)
                if name == 'vcomp140.dll':
                    shutil.copyfile(args.redist, out)
                else:
                    member = 'rife-ncnn-vulkan-20221029-windows/' + name
                    with upstream.open(member) as src, out.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                if sha256(out) != expected:
                    raise ValueError('Unexpected RIFE component: ' + name)
        for name in spec['files']:
            out = dest / name
            out.parent.mkdir(parents=True, exist_ok=True)
            (stage / name).replace(out)


if __name__ == '__main__':
    main()
