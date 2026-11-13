# SPDX-License-Identifier: GPL-3.0-only
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

from build_inputs import SOURCE, sha256, source_identity
from generate_fixture import generate


def run(command, log, env, timeout=1800):
    print(log.name, flush=True)
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(list(map(str, command)), cwd=SOURCE, env=env,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{log.name}: exit {result.returncode}\n' + log.read_text(errors='replace')[-6000:])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--qt-root', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, default=SOURCE / '.build-linux')
    args = parser.parse_args()
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise ValueError('This prototype requires native Linux x86_64')
    import PySide6
    from PySide6.QtCore import qVersion
    if qVersion() != '6.12.0': raise ValueError('Expected Qt 6.12.0')
    directory = args.build_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'temp').mkdir()
    identity = source_identity()
    qt_runtime = Path(PySide6.__file__).resolve().parent / 'Qt/lib'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', CADENCE_RENDERER='software',
               PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'],
               CADENCE_PREFS=str(directory / 'preferences.json'), CADENCE_CACHE=str(directory / 'cache'),
               CADENCE_SYNC_ENDPOINT=str(directory / 'sync.json'), CADENCE_DISABLE_UPDATES='1',
               TMPDIR=str(directory / 'temp'), XDG_CONFIG_HOME=str(directory / 'config'),
               XDG_CACHE_HOME=str(directory / 'xdg-cache'), XDG_STATE_HOME=str(directory / 'state'))
    generate(SOURCE / 'assets/Demonstration.mp4')
    run(['cmake', '-S', SOURCE / 'native', '-B', directory / 'native', '-G', 'Ninja',
         '-DCMAKE_BUILD_TYPE=Release', f'-DCMAKE_PREFIX_PATH={args.qt_root.resolve()}',
         f'-DCADENCE_QT_RUNTIME_DIR={qt_runtime}'], directory / 'cmake-configure.log', env)
    run(['cmake', '--build', directory / 'native', '--parallel', '4'], directory / 'cmake-build.log', env)
    native_check = 'import native_graphics,native_render; lib=native_graphics.load_library(); assert native_render._library() is not None; print(lib._name)'
    run([sys.executable, '-c', native_check], directory / 'native-load.log', env)
    tests = json.loads((SOURCE / 'packaging/linux-tests.json').read_text())
    run([sys.executable, '-m', 'pytest', '-q', *tests, '--basetemp', directory / 'pytest',
         '--junitxml', directory / 'pytest.xml'], directory / 'pytest.log', env)
    run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', directory / 'dist',
         '--workpath', directory / 'pyinstaller', SOURCE / 'Cadence.spec'], directory / 'pyinstaller.log', env)
    payload = directory / 'dist/Cadence'
    smoke = {}
    for language in ('fr', 'en'):
        smoke_env = dict(env, CADENCE_LANGUAGE=language, CADENCE_SMOKE_MEDIA=str(SOURCE / 'assets/Demonstration.mp4'))
        run([payload / 'Cadence', '--self-test', directory / f'smoke-{language}'], directory / f'smoke-{language}.log', smoke_env, 600)
        result_file = directory / f'smoke-{language}/result.json'
        result = json.loads(result_file.read_text())
        if result.get('status') != 'passed' or not result.get('frozen') or not result.get('native_pixels'):
            raise ValueError(f'Incomplete packaged test: {language}')
        smoke[language] = sha256(result_file)
    if identity['source_sha256'] != source_identity()['source_sha256']:
        raise ValueError('Sources changed during validation')
    version = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)", (SOURCE / 'app.py').read_text(), re.M)[1]
    record = {'status': 'passed', 'version': version, 'scope': 'Linux build; clean desktop validation separate',
              'source': identity, 'platform': platform.platform(), 'python': platform.python_version(),
              'qt': qVersion(), 'packages': {name: importlib.metadata.version(name) for name in
                  ('PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'av', 'numpy', 'pyinstaller', 'pytest')},
              'ffmpeg_sha256': sha256(SOURCE / 'vendor/ffmpeg'), 'smoke': smoke,
              'pytest_xml_sha256': sha256(directory / 'pytest.xml'),
              'payload': {str(p.relative_to(payload)): sha256(p) for p in sorted(payload.rglob('*')) if p.is_file()}}
    (directory / 'verification.json').write_text(json.dumps(record, indent=2))
    print('Native Linux build and packaged FR/EN core tests passed.')


if __name__ == '__main__':
    main()
