# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import shutil
import sys
import tarfile

from build_inputs import SOURCE, sha256, verify_tree
from fetch_ffmpeg_linux import EXECUTABLE_SHA256
from build_deb import build as build_deb
from release import archive, validate_build


def package(args):
    if sys.platform != 'linux': raise ValueError('Linux packaging must run on Linux')
    directory, output = args.build_dir.resolve(), args.output.resolve()
    stage = directory / 'release/Cadence'
    if stage.exists(): raise FileExistsError(f'Use a fresh staging directory: {stage}')
    payload = directory / 'dist/Cadence'
    for path in payload.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(payload.resolve()):
            raise ValueError('Runtime link escapes payload')
    shutil.copytree(payload, stage, symlinks=False)
    evidence, identity = validate_build(directory, stage)
    version = evidence['version']
    dependency_root = args.dependency_root.resolve()
    lock_path = SOURCE / 'packaging/third-party-linux.lock.json'
    lock = json.loads(lock_path.read_text())
    verify_tree(dependency_root, lock['files'])
    if sha256(stage / '_internal/vendor/ffmpeg') != EXECUTABLE_SHA256: raise ValueError('Unexpected Linux FFmpeg')
    if not (stage / '_internal/native/bin/libcadence_native.so').is_file(): raise ValueError('Missing native Linux library')
    for item in stage.rglob('*'):
        if item.name.lower() in ('demonstration.mp4', 'id_ed25519', 'seed.iso'):
            raise ValueError(f'Unexpected runtime resource: {item.name}')
    output.mkdir(parents=True, exist_ok=True)
    notices = stage / 'Licences'
    shutil.copytree(dependency_root / 'Notices', notices)
    shutil.copyfile(SOURCE / 'COPYING.txt', notices / 'Cadence-GPLv3.txt')
    shutil.copyfile(SOURCE / 'LICENSING.txt', notices / 'Cadence-NOTICE.txt')
    sources = output / f'Cadence-{version}-sources.zip'
    archive(sources, {f'cadence/{name}': SOURCE / name for name in identity['files']})
    shutil.copyfile(sources, notices / 'Cadence-sources.zip')
    groups=[]; current={}; size=0
    for name in sorted(lock['files']):
        path=dependency_root/name
        if current and size+path.stat().st_size>1_700_000_000:
            groups.append(current); current={}; size=0
        current[name]=path; size+=path.stat().st_size
    if current: groups.append(current)
    third=[]
    for index, files in enumerate(groups, 1):
        name=f'Cadence-{version}-Linux-third-party-sources-{index:02d}.zip'
        path=output/name; archive(path, files); third.append(path)
    (notices/'THIRD-PARTY-SOURCES.txt').write_text(
        'Corresponding third-party sources / Sources tierces correspondantes\n\n'
        f'https://github.com/BaoGM/cadence/releases/tag/v{version}\n\n'+
        '\n'.join(f'{path.name}\nSHA256 {sha256(path)}' for path in third)+
        '\n\nAll parts are independent ZIP archives. Extract each into the same directory.\n'
        'Chaque partie est une archive ZIP indépendante. Extraire toutes les parties dans le même dossier.\n',encoding='utf-8')
    shutil.copyfile(SOURCE/'docs/LINUX.txt',stage/'LIRE-MOI-LINUX.txt')
    portable=output/f'Cadence-{version}-Linux-x86_64.tar.gz'
    with tarfile.open(portable,'w:gz',compresslevel=6) as target:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                info=target.gettarinfo(str(path),'Cadence/'+path.relative_to(stage).as_posix())
                info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
                info.mode=0o755 if path.name=='Cadence' or path.name=='ffmpeg' else 0o644
                with path.open('rb') as stream:target.addfile(info,stream)
    with tarfile.open(portable) as target:
        for entry in target:
            if not entry.isfile() or not entry.name.startswith('Cadence/') or '..' in Path(entry.name).parts:
                raise ValueError('Unsafe Linux archive entry')
    deb = build_deb(version, stage, output, directory / 'deb-root')
    artifacts={path.name:sha256(path) for path in [sources,*third,portable,deb]}
    provenance={'version':version,'platform':'linux-x86_64','status':'prerelease',
        'source':identity,'build_verification_sha256':sha256(directory/'verification.json'),
        'dependency_manifest_sha256':sha256(lock_path),'artifacts':artifacts,
        'target':'Ubuntu 24.04 x86_64; X11 capture', 'clean_desktop_validation':'See release validation attachment'}
    proof=output/f'Cadence-{version}-provenance.json';proof.write_text(json.dumps(provenance,indent=2))
    artifacts[proof.name]=sha256(proof)
    (output/f'Cadence-{version}-sha256.json').write_text(json.dumps(artifacts,indent=2))
    print(json.dumps(artifacts,indent=2),flush=True)
