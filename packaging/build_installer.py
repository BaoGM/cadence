# SPDX-License-Identifier: GPL-3.0-only
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parents[1]
PROJECT = SOURCE
EXTENSIONS = ('.cadence', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.mpg', '.mpeg', '.mts', '.mxf', '.gif', '.wav', '.mp3')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compiler_path(explicit=None):
    candidates = [explicit, os.environ.get('INNO_SETUP_COMPILER'),
                  SOURCE / '.deps/inno/ISCC.exe', shutil.which('ISCC.exe'),
                  Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise SystemExit('Compilateur Inno Setup introuvable. Définir INNO_SETUP_COMPILER ou utiliser --compiler.')


def build(version, payload, output, compiler=None, test_build=False):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Version attendue : major.minor.patch')
    payload = Path(payload).resolve()
    output = Path(output).resolve()
    for required in ('Cadence.exe', '_internal', 'Licences'):
        if not (payload / required).exists():
            raise FileNotFoundError(payload / required)
    import pefile
    with pefile.PE(str(payload / 'Cadence.exe'), fast_load=True) as executable:
        executable.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        info = executable.VS_FIXEDFILEINFO[0]
        actual = f'{info.FileVersionMS >> 16}.{info.FileVersionMS & 65535}.{info.FileVersionLS >> 16}'
    if actual != version:
        raise ValueError(f'Exécutable {actual}, installateur demandé {version}')
    work = output / 'installer-build' / (version + ('-test' if test_build else ''))
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for file in sorted(payload.rglob('*')):
        if file.is_symlink() or file.is_junction():
            raise ValueError(f'Lien interdit dans la livraison : {file}')
        if file.is_file():
            relative = file.relative_to(payload)
            if relative.parts[0] == 'uninstall':
                raise ValueError('Le dossier livré doit être portable, sans désinstalleur existant.')
            files.append((str(relative), sha256(file)))
    manifest = work / 'files.txt'
    manifest.write_text(''.join(f'{digest}|{relative}\n' for relative, digest in files), encoding='utf-8-sig')
    associations = work / 'associations.iss'
    lines = []
    for extension in EXTENSIONS:
        progid = 'Cadence.Installed.Project' if extension == '.cadence' else 'Cadence.Installed.Media'
        lines.extend([
            f'Root: HKA; Subkey: "{{#RegistryBase}}\\Classes\\{extension}\\OpenWithProgids"; ValueName: "{progid}"; ValueType: string; ValueData: ""; Flags: uninsdeletevalue; Tasks: filetypes',
            f'Root: HKA; Subkey: "{{#RegistryBase}}\\Cadence\\InstalledCapabilities\\FileAssociations"; ValueName: "{extension}"; ValueType: string; ValueData: "{progid}"; Tasks: filetypes',
        ])
    associations.write_text('\n'.join(lines), encoding='utf-8-sig')
    compiler = compiler_path(compiler)
    command = [str(compiler), f'/DAppVersion={version}', f'/DPayloadDir={payload}',
               f'/DManifestFile={manifest}', f'/DAssociationsFile={associations}', f'/O{output}']
    if test_build:
        command.append('/DTestBuild=1')
    command.append(str(SOURCE / 'packaging/Cadence.iss'))
    log = work / 'compiler.log'
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0))
    if result.returncode:
        raise RuntimeError(f'Échec Inno Setup ({result.returncode}). Journal : {log}\n' + log.read_text(encoding='utf-8', errors='replace')[-3000:])
    installer = output / f'Cadence-{version}-Setup.exe'
    digest = sha256(installer)
    metadata = {'version': version, 'installer': str(installer), 'sha256': digest,
                'compiler': str(compiler), 'compiler_sha256': sha256(compiler),
                'file_count': len(files), 'payload_bytes': sum((payload / name).stat().st_size for name, _ in files),
                'test_build': test_build}
    (work / 'result.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if not test_build:
        checksum_file = output / f'Cadence-{version}-sha256.json'
        checks = json.loads(checksum_file.read_text(encoding='utf-8')) if checksum_file.exists() else {}
        checks[installer.name] = digest
        checksum_file.write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(f'{installer}\n{installer.stat().st_size / 1024**2:.1f} Mo\nSHA256 {digest}')
    return installer


def main():
    parser = argparse.ArgumentParser(description='Créer l’installateur Windows d’une livraison Cadence existante.')
    parser.add_argument('--version', default=re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)", (SOURCE / 'app.py').read_text(encoding='utf-8'), re.M)[1])
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compiler', type=Path)
    parser.add_argument('--test-build', action='store_true')
    args = parser.parse_args()
    output = args.output or (PROJECT / 'work/installer-tests/packages' if args.test_build else PROJECT / 'outputs')
    build(args.version, args.payload or PROJECT / f'outputs/v{args.version}/Cadence', output, args.compiler, args.test_build)


if __name__ == '__main__':
    main()
