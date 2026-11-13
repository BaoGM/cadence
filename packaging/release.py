# SPDX-License-Identifier: GPL-3.0-only
import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

from audit_release import audit
from build_installer import build
from build_inputs import SOURCE, sha256, source_identity, verify_tree


def archive(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for name, file in sorted(files.items()):
            stored = file.suffix.lower() in ('.zip', '.gz', '.xz', '.bz2', '.7z')
            target.write(file, name, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(path) as target:
        if target.testzip() is not None:
            raise RuntimeError(f'Invalid archive: {path.name}')


def validate_build(directory, payload):
    evidence = json.loads((directory / 'verification.json').read_text(encoding='utf-8'))
    identity = source_identity()
    if evidence['status'] != 'passed' or evidence['source']['source_sha256'] != identity['source_sha256']:
        raise ValueError('Build validation does not match current sources')
    verify_tree(payload, evidence['payload'])
    if sha256(directory / 'pytest.xml') != evidence['pytest_xml_sha256']:
        raise ValueError('Changed test report')
    for language in ('fr', 'en'):
        result_file = directory / f'smoke-{language}/result.json'
        if sha256(result_file) != evidence['smoke'][language]:
            raise ValueError('Changed executable test report')
        result = json.loads(result_file.read_text(encoding='utf-8'))
        if result['status'] != 'passed' or not result['frozen'] or result['language'] != language:
            raise ValueError(f'Executable self-test failed: {language}')
        for feature in ('native_mixed_rates', 'background_audio', 'reference_sequence', 'timecode_overlay', 'native_pixels'):
            if not result.get(feature):
                raise ValueError(f'Missing executable test: {feature}')
    return evidence, identity


def main():
    parser = argparse.ArgumentParser(description='Package verified unsigned Cadence artifacts.')
    parser.add_argument('--build-dir', type=Path, default=SOURCE / '.build')
    parser.add_argument('--dependency-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=SOURCE / 'dist/unsigned')
    parser.add_argument('--compiler', type=Path)
    parser.add_argument('--platform', choices=('windows','linux'), default='linux' if sys.platform=='linux' else 'windows')
    args = parser.parse_args()
    if args.platform == 'linux':
        from release_linux import package
        package(args)
        return
    directory, output = args.build_dir.resolve(), args.output.resolve()
    payload = directory / 'dist/Cadence'
    evidence, identity = validate_build(directory, payload)
    lock = json.loads((SOURCE / 'packaging/third-party.lock.json').read_text(encoding='utf-8'))
    verify_tree(args.dependency_root, lock['files'])
    version = evidence['version']
    output.mkdir(parents=True, exist_ok=True)
    stage = directory / 'release/Cadence'
    if stage.exists():
        raise FileExistsError(f'Use a fresh release staging directory: {stage}')
    shutil.copytree(payload, stage)
    shutil.copytree(args.dependency_root / 'Notices', stage / 'Licences')
    shutil.copyfile(SOURCE / 'COPYING.txt', stage / 'Licences/Cadence-GPLv3.txt')
    shutil.copyfile(SOURCE / 'LICENSING.txt', stage / 'Licences/Cadence-NOTICE.txt')
    third = output / f'Cadence-{version}-third-party-sources.zip'
    archive(third, {name: args.dependency_root / name for name in lock['files']})
    sources = output / f'Cadence-{version}-sources.zip'
    archive(sources, {f'cadence/{name}': SOURCE / name for name in identity['files']})
    shutil.copyfile(sources, stage / 'Licences/Cadence-sources.zip')
    (stage / 'Licences/THIRD-PARTY-SOURCES.txt').write_text(
        f'Third-party sources / Sources tierces\n\n{third.name}\nSHA256: {sha256(third)}\n\n'
        'Offer this archive beside the binaries, at the same download location and at no additional charge. '
        'It contains the sources, recipes, patches and original notices of bundled libraries. '
        'It is not needed to run Cadence.\n\n'
        'Proposer cette archive avec les binaires, au même emplacement de téléchargement, sans frais supplémentaires. '
        'Elle contient les sources, recettes, correctifs et notices originales des bibliothèques livrées. '
        'Elle ne sert pas à exécuter Cadence.\n', encoding='utf-8')
    (stage / 'Associer Cadence.cmd').write_bytes(b'@echo off\r\nstart "" "%~dp0Cadence.exe" --register-associations\r\n')
    report = audit(stage)
    portable = output / f'Cadence-{version}-Windows.zip'
    archive(portable, {f'Cadence/{f.relative_to(stage).as_posix()}': f for f in stage.rglob('*') if f.is_file()})
    installer = build(version, stage, output, args.compiler)
    artifacts = {f.name: sha256(f) for f in (sources, third, portable, installer)}
    provenance = {'status': 'unsigned', 'version': version, 'source': identity,
                  'tools': evidence['tools'], 'dependency_manifest_sha256': sha256(SOURCE / 'packaging/third-party.lock.json'),
                  'verification_sha256': sha256(directory / 'verification.json'), 'audit': report, 'artifacts': artifacts}
    (output / f'Cadence-{version}-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    (output / f'Cadence-{version}-sha256.json').write_text(json.dumps(artifacts, indent=2), encoding='utf-8')
    print(json.dumps({'version': version, 'status': 'unsigned', 'artifacts': artifacts}, indent=2))


if __name__ == '__main__':
    main()
