# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
from types import SimpleNamespace

import pytest

import sync3d_setup as setup


@pytest.fixture
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, 'WINDOWS', False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('BLENDER_USER_SCRIPTS', raising=False)
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    monkeypatch.setattr(setup.shutil, 'which', lambda name: None)
    import psutil
    monkeypatch.setattr(psutil, 'process_iter', lambda fields: [])
    return tmp_path


def test_linux_installed_versions_and_existing_preferences(folders):
    root = folders / '.config/blender'
    for name in ('5.3', '4.5', '3.6', 'backup'):
        (root / name).mkdir(parents=True)
    preferences = root / '5.3/userpref.blend'
    preferences.write_bytes(b'existing preferences')
    assert setup.blender_script_folders() == [root / '4.5/scripts', root / '5.3/scripts']
    assert preferences.read_bytes() == b'existing preferences'


def test_linux_running_portable_blender_before_preferences(folders, monkeypatch):
    import psutil
    install = folders / 'Downloads/blender-5.3.0-linux-x64'
    (install / '5.3/scripts').mkdir(parents=True)
    monkeypatch.setattr(psutil, 'process_iter', lambda fields: [
        SimpleNamespace(info={'name': 'blender', 'exe': str(install / 'blender')})])
    assert setup.blender_script_folders() == [folders / '.config/blender/5.3/scripts']


@pytest.mark.parametrize('custom', ['absolute', 'relative'])
def test_linux_config_directory(folders, monkeypatch, custom):
    root = folders / ('custom' if custom == 'absolute' else '.config')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(root) if custom == 'absolute' else 'relative')
    (root / 'blender/5.3').mkdir(parents=True)
    assert setup.blender_script_folders() == [root / 'blender/5.3/scripts']


def test_windows_blender_detection_preserved(folders, monkeypatch):
    monkeypatch.setattr(setup, 'WINDOWS', True)
    monkeypatch.setenv('APPDATA', str(folders / 'Roaming'))
    monkeypatch.setenv('ProgramFiles', str(folders / 'Programs'))
    (folders / 'Programs/Blender Foundation/Blender 5.3/5.3').mkdir(parents=True)
    assert setup.blender_script_folders() == [folders / 'Roaming/Blender Foundation/Blender/5.3/scripts']


def test_explicit_scripts_directory_and_missing_blender(folders, monkeypatch):
    with pytest.raises(OSError, match='Blender'):
        setup.blender_script_folders()
    monkeypatch.setenv('BLENDER_USER_SCRIPTS', str(folders / 'custom scripts'))
    assert setup.blender_script_folders() == [folders / 'custom scripts']


def test_unvalidated_maya_does_not_install_on_linux(folders):
    with pytest.raises(OSError, match='Maya'):
        setup.install_connector('maya')


def test_linux_host_choice_keeps_windows_maya_available(monkeypatch):
    from PySide6.QtWidgets import QApplication, QComboBox
    import sync3d_dialog
    app = QApplication.instance() or QApplication([])
    for windows in (False, True):
        monkeypatch.setattr(sync3d_dialog, 'WINDOWS', windows)
        choices = QComboBox()
        sync3d_dialog.add_hosts(choices)
        assert choices.model().item(choices.findData('blender')).isEnabled()
        assert choices.model().item(choices.findData('maya')).isEnabled() == windows
