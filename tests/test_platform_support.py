# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path

import pytest

import platform_support


def test_windows_storage_paths_are_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_support, 'WINDOWS', True)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert platform_support.config_directory() == tmp_path / 'CadenceStudio'
    assert platform_support.cache_directory() == tmp_path / 'CadenceStudio/cache'
    assert platform_support.state_directory() == tmp_path / 'CadenceStudio'


def test_linux_storage_uses_xdg_and_ignores_windows_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_support, 'WINDOWS', False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'windows'))
    for variable, name in [('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state')]:
        monkeypatch.setenv(variable, str(tmp_path / name))
    assert platform_support.config_directory() == tmp_path / 'config/CadenceStudio'
    assert platform_support.cache_directory() == tmp_path / 'cache/CadenceStudio'
    assert platform_support.state_directory() == tmp_path / 'state/CadenceStudio'


@pytest.mark.parametrize('value', ['', 'relative/path'])
def test_relative_xdg_setting_uses_home(monkeypatch, tmp_path, value):
    monkeypatch.setattr(platform_support, 'WINDOWS', False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('XDG_CONFIG_HOME', value)
    assert platform_support.config_directory() == tmp_path / '.config/CadenceStudio'


def test_test_profile_overrides_platform_storage(monkeypatch, tmp_path):
    import preferences, media, diagnostics
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'profile/preferences.json'))
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    assert preferences.preference_path() == tmp_path / 'profile/preferences.json'
    assert diagnostics.log_directory() == tmp_path / 'profile/logs'
    assert media.cache_root() == tmp_path / 'cache'


def test_linux_update_manager_never_requests_windows_packages(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    import update_ui
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    monkeypatch.setattr(update_ui, 'WINDOWS', False)
    manager = update_ui.UpdateManager(window, '1.16.1')
    def unexpected(*args): raise AssertionError('Linux must not request a Windows update')
    monkeypatch.setattr(manager, 'run', unexpected)
    manager.start()
    manager.check_now()
    assert not manager.busy
    manager.stop()
    window.close()


def test_cache_cleanup_preserves_media_and_protected_entries(monkeypatch, tmp_path):
    from cache_tools import cache_bytes, clear_cache
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path))
    generated = tmp_path / ('a' * 24)
    protected = tmp_path / ('b' * 24)
    source = tmp_path / ('c' * 24)
    for folder in (generated, protected, source): folder.mkdir()
    (generated / 'preview.avi').write_bytes(b'generated')
    (protected / 'preview.avi').write_bytes(b'protected')
    (source / 'original.mp4').write_bytes(b'source')
    assert cache_bytes() == 18
    assert clear_cache([protected / 'preview.avi']) == (1, 1, 0, 9)
    assert not generated.exists()
    assert (protected / 'preview.avi').read_bytes() == b'protected'
    assert (source / 'original.mp4').read_bytes() == b'source'
