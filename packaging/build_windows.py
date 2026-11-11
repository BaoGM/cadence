# SPDX-License-Identifier: GPL-3.0-only
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from build_inputs import SOURCE, sha256, source_identity
from fetch_ffmpeg import EXECUTABLE_SHA256
from generate_fixture import generate


def compiler_environment(msvc, qt, lock):
    env = os.environ.copy()
    vc = msvc / 'VC/Tools/MSVC' / lock['msvc']
    sdk = msvc / 'Windows Kits/10'
    if not sdk.is_dir():
        sdk = Path(os.environ.get('WindowsSdkDir', 'C:/Program Files (x86)/Windows Kits/10'))
    sdk_version = lock['windows_sdk']
    required = [vc / 'bin/Hostx64/x64/cl.exe', sdk / 'Lib' / sdk_version / 'um/x64/kernel32.lib', qt / 'lib/cmake/Qt6/Qt6Config.cmake']
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    import cmake
    binaries = [vc / 'bin/Hostx64/x64', sdk / 'bin' / sdk_version / 'x64', Path(sys.executable).parent, Path(cmake.CMAKE_BIN_DIR)]
    env['PATH'] = os.pathsep.join(map(str, binaries)) + os.pathsep + env['PATH']
    env['INCLUDE'] = os.pathsep.join(map(str, [vc / 'include', *[sdk / 'Include' / sdk_version / name for name in ('ucrt', 'shared', 'um', 'winrt')]]))
    env['LIB'] = os.pathsep.join(map(str, [vc / 'lib/x64', sdk / 'Lib' / sdk_version / 'ucrt/x64', sdk / 'Lib' / sdk_version / 'um/x64']))
    env['CMAKE_PREFIX_PATH'] = str(qt)
    return env, required[0]


def run(command, log, env, timeout=1800):
    print(log.name, flush=True)
    command = list(map(str, command))
    command[0] = shutil.which(command[0], path=env['PATH']) or command[0]
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=SOURCE, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'{log.name}: exit {result.returncode}\n' + log.read_text(encoding='utf-8', errors='replace')[-6000:])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--msvc-root', type=Path, required=True)
    parser.add_argument('--qt-root', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, default=SOURCE / '.build')
    args = parser.parse_args()
    lock = json.loads((SOURCE / 'packaging/toolchain.lock.json').read_text(encoding='utf-8'))
    if platform.python_version() != lock['python'] or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Build requires pinned Python x64 version')
    packages = {}
    for line in (SOURCE / 'requirements-build.lock').read_text(encoding='utf-8').splitlines():
        name, version = line.split(' --hash=', 1)[0].split('==')
        actual = importlib.metadata.version(name)
        if actual != version:
            raise ValueError(f'Package mismatch: {name}: expected {version}, found {actual}')
        packages[name] = actual
    directory = args.build_dir.resolve()
    if directory.exists():
        raise FileExistsError('Use a fresh build directory; validation never reuses old reports.')
    directory.mkdir(parents=True)
    (directory / 'temp').mkdir()
    identity = source_identity()
    env, compiler = compiler_environment(args.msvc_root.resolve(), args.qt_root.resolve(), lock)
    env.update(QT_QPA_PLATFORM='offscreen', CADENCE_RENDERER='software',
               CADENCE_CACHE=str(directory / 'cache'), CADENCE_PREFS=str(directory / 'preferences.json'),
               CADENCE_LANGUAGE='fr', PYTHONUTF8='1', TEMP=str(directory / 'temp'), TMP=str(directory / 'temp'))
    if sha256(SOURCE / 'vendor/ffmpeg.exe') != EXECUTABLE_SHA256:
        raise ValueError('Unexpected FFmpeg')
    generate(SOURCE / 'assets/Demonstration.mp4')
    run(['cmake', '-S', SOURCE / 'native', '-B', directory / 'native', '-G', 'Ninja',
         '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_TRY_COMPILE_CONFIGURATION=Release', '-DCMAKE_CXX_COMPILER=cl',
         '-DCMAKE_EXE_LINKER_FLAGS=/MANIFEST:NO', '-DCMAKE_SHARED_LINKER_FLAGS=/MANIFEST:NO'], directory / 'cmake-configure.log', env)
    run(['cmake', '--build', directory / 'native', '--parallel', '2'], directory / 'cmake-build.log', env)
    tests = json.loads((SOURCE / 'packaging/headless-tests.json').read_text(encoding='utf-8'))
    run([sys.executable, '-m', 'pytest', '-q', *tests, '--basetemp', directory / 'pytest', '--junitxml', directory / 'pytest.xml'], directory / 'pytest.log', env)
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', directory / 'dist', '--workpath', directory / 'pyinstaller', SOURCE / 'Cadence.spec'], directory / 'pyinstaller.log', env)
    payload = directory / 'dist/Cadence'
    smoke = {}
    for language in ('fr', 'en'):
        smoke_env = dict(env, CADENCE_LANGUAGE=language, CADENCE_SMOKE_MEDIA=str(SOURCE / 'assets/Demonstration.mp4'))
        run([payload / 'Cadence.exe', '--self-test', directory / f'smoke-{language}'], directory / f'smoke-{language}.log', smoke_env, 420)
        result_file = directory / f'smoke-{language}/result.json'
        result = json.loads(result_file.read_text(encoding='utf-8'))
        if result.get('status') != 'passed' or not result.get('frozen') or result.get('language') != language:
            raise ValueError(f'Invalid smoke test: {language}')
        smoke[language] = sha256(result_file)
    if source_identity()['source_sha256'] != identity['source_sha256']:
        raise ValueError('Source files changed during build')
    version = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)", (SOURCE / 'app.py').read_text(encoding='utf-8'), re.M)[1]
    tools = {'python': platform.python_version(), 'python_exe_sha256': sha256(sys.executable), 'packages': packages,
             'msvc': lock['msvc'], 'compiler_sha256': sha256(compiler), 'windows_sdk': lock['windows_sdk'], 'qt': lock['qt'],
             'qt_core_sha256': sha256(args.qt_root / 'bin/Qt6Core.dll'), 'ffmpeg_sha256': EXECUTABLE_SHA256}
    record = {'status': 'passed', 'version': version, 'source': identity, 'tools': tools, 'smoke': smoke,
              'pytest_xml_sha256': sha256(directory / 'pytest.xml'),
              'payload': {f.relative_to(payload).as_posix(): sha256(f) for f in sorted(payload.rglob('*')) if f.is_file()}}
    (directory / 'verification.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('Build and FR/EN verification passed.', flush=True)


if __name__ == '__main__':
    import msvcrt
    lock_path = SOURCE / '.deps/build.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as build_lock:
        if build_lock.tell() == 0:
            build_lock.write(b'0')
            build_lock.flush()
        build_lock.seek(0)
        msvcrt.locking(build_lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            main()
        finally:
            build_lock.seek(0)
            msvcrt.locking(build_lock.fileno(), msvcrt.LK_UNLCK, 1)
