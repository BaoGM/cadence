# SPDX-License-Identifier: GPL-3.0-only
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import winreg

from build_installer import PROJECT, SOURCE, sha256

ROOT = PROJECT / 'work/installer-tests'
PACKAGES = ROOT / 'packages'
INSTALL = ROOT / 'Cadence'
PRIVATE_REGISTRY = r'Software\CadenceInstallerTests'
TEST_HIVE = winreg.HKEY_CURRENT_USER


def run(executable, *arguments):
    process = subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', *arguments],
                             timeout=240, creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode:
        raise RuntimeError(f'Installateur : code {process.returncode}')


def snapshot_preferences():
    folder = Path(os.environ['LOCALAPPDATA']) / 'CadenceStudio'
    return {str(path): sha256(path) for name in ('preferences.json', 'workspaces.json', 'last_session.json')
            if (path := folder / name).is_file()}


def registry_value(path, name='', hive=None):
    try:
        with winreg.OpenKey(TEST_HIVE if hive is None else hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def delete_test_registry(path=PRIVATE_REGISTRY):
    assert path == PRIVATE_REGISTRY or path.startswith(PRIVATE_REGISTRY + '\\')
    try:
        with winreg.OpenKey(TEST_HIVE, path, 0, winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_test_registry(path + '\\' + child)
        winreg.DeleteKeyEx(TEST_HIVE, path, winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        pass


def main():
    global ROOT, INSTALL, TEST_HIVE
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous', default='1.10.8')
    parser.add_argument('--current', default='1.11.0')
    parser.add_argument('--all-users', action='store_true')
    args = parser.parse_args()
    if args.all_users:
        assert ctypes.windll.shell32.IsUserAnAdmin(), 'Exécuter le test depuis un terminal administrateur.'
        TEST_HIVE = winreg.HKEY_LOCAL_MACHINE
    mode = '/ALLUSERS' if args.all_users else '/CURRENTUSER'
    ROOT = ROOT / (args.current + ('-admin' if args.all_users else '-user'))
    INSTALL = ROOT / 'Cadence'
    ROOT.mkdir(parents=True, exist_ok=True)
    assert not INSTALL.exists(), 'Le dossier de test doit être neuf.'
    before = snapshot_preferences()
    production_keys = [r'Software\Classes\CadenceStudio.Project\shell\open\command',
                       r'Software\Classes\Cadence.Video\shell\open\command',
                       r'Software\Classes\Cadence.Installed.Media\shell\open\command']
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    association_before = [registry_value(key, hive=hive) for hive in hives for key in production_keys]
    results = {}
    try:
        for version in (args.previous, args.current):
            run(PACKAGES / f'Cadence-{version}-Setup.exe', mode, f'/DIR={INSTALL}', '/TASKS=filetypes',
                '/NOCLOSEAPPLICATIONS', '/LANG=french', f'/LOG={ROOT / (version + ".log")}')
            source = PROJECT / f'outputs/v{version}/Cadence'
            expected = {p.relative_to(source): sha256(p) for p in source.rglob('*') if p.is_file()}
            assert all((INSTALL / relative).is_file() and sha256(INSTALL / relative) == digest for relative, digest in expected.items())
            assert (INSTALL / 'Test Start Menu/Cadence.lnk').is_file()
            command = registry_value(PRIVATE_REGISTRY + r'\Classes\Cadence.Installed.Media\shell\open\command')
            assert command == f'"{INSTALL / "Cadence.exe"}" "%1"'
            assert registry_value(PRIVATE_REGISTRY + r'\Cadence\InstalledCapabilities\FileAssociations', '.wav') == 'Cadence.Installed.Media'
            if version == args.current:
                assert registry_value(PRIVATE_REGISTRY + r'\Classes\.wav\OpenWithProgids', 'Cadence.Installed.Media') == ''
                uninstall_key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Cadence.Installer.Test_is1'
                assert registry_value(uninstall_key, 'DisplayName') == 'Cadence Installer Test'
                assert registry_value(uninstall_key, 'DisplayVersion') == args.current
                results['separate_name_and_version'] = True
            log = (ROOT / (version + '.log')).read_text(encoding='utf-8-sig')
            assert 'Administrative install mode: ' + ('Yes' if args.all_users else 'No') in log
            results[version] = {'files_verified': len(expected), 'shortcut': True, 'associations': True}
            if version == args.previous:
                (INSTALL / 'personal.cadence').write_text('User project - preserve', encoding='utf-8')
                obsolete = INSTALL / '_internal/obsolete-test.dll'
                obsolete.write_bytes(b'old library')
                changed = INSTALL / '_internal/modified-test.dll'
                changed.write_bytes(b'user modification')
                with (INSTALL / 'uninstall/installed-files.txt').open('a', encoding='utf-8') as manifest:
                    manifest.write(sha256(obsolete) + '|_internal\\obsolete-test.dll\n')
                    manifest.write(hashlib.sha256(b'original').hexdigest() + '|_internal\\modified-test.dll\n')
            else:
                assert not (INSTALL / '_internal/obsolete-test.dll').exists()
                assert (INSTALL / '_internal/modified-test.dll').read_bytes() == b'user modification'
                assert (INSTALL / 'personal.cadence').read_text(encoding='utf-8') == 'User project - preserve'
        run(PACKAGES / f'Cadence-{args.current}-Setup.exe', mode, '/TASKS=filetypes', '/NOCLOSEAPPLICATIONS',
            '/LANG=english', f'/LOG={ROOT / "reinstall.log"}')
        assert sha256(INSTALL / 'Cadence.exe') == sha256(PROJECT / f'outputs/v{args.current}/Cadence/Cadence.exe')
        results['remembered_install_path'] = True
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM='offscreen', CADENCE_RENDERER='software', CADENCE_LANGUAGE='en',
                   CADENCE_SMOKE_MEDIA=str(SOURCE / 'assets/Demonstration.mp4'))
        smoke = ROOT / 'installed-smoke'
        result = subprocess.run([str(INSTALL / 'Cadence.exe'), '--self-test', str(smoke)], env=env,
                                timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0
        assert json.loads((smoke / 'result.json').read_text(encoding='utf-8'))['status'] == 'passed'
        results['installed_application'] = True
    finally:
        uninstaller = INSTALL / 'uninstall/unins000.exe'
        if uninstaller.exists():
            run(uninstaller, f'/LOG={ROOT / "uninstall.log"}')
        results['preferences_preserved'] = snapshot_preferences() == before
        results['portable_associations_preserved'] = [registry_value(key, hive=hive) for hive in hives for key in production_keys] == association_before
    assert results['preferences_preserved'] and results['portable_associations_preserved']
    assert not (INSTALL / 'Cadence.exe').exists()
    assert not (INSTALL / 'Test Start Menu/Cadence.lnk').exists()
    assert (INSTALL / 'personal.cadence').is_file()
    assert registry_value(PRIVATE_REGISTRY + r'\Classes\Cadence.Installed.Media\shell\open\command') is None
    assert registry_value(r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Cadence.Installer.Test_is1', 'DisplayName') is None
    results['uninstall'] = True
    results['user_files_preserved'] = True
    results['administrative_mode'] = args.all_users
    delete_test_registry()
    (ROOT / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
