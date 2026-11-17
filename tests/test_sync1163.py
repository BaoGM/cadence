# SPDX-License-Identifier: GPL-3.0-only
import logging
import os
from pathlib import Path
import py_compile
import sys
from types import ModuleType

import pytest

from integrations.cadence_runtime import load_source
from sync3d_setup import install_connector
from test_sync1120 import application


@pytest.fixture
def connector(tmp_path, monkeypatch, application):
    folder = tmp_path / 'profil avec espaces et accents é'
    monkeypatch.setenv('CADENCE_SYNC_ENDPOINT', str(folder / 'endpoint.json'))
    monkeypatch.setenv('MAYA_APP_DIR', str(folder / 'maya'))
    monkeypatch.setenv('BLENDER_USER_SCRIPTS', str(folder / 'blender'))
    for name in ('cadence_runtime', 'cadence_autostart', 'cadence_bridge'):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield folder
    for name in ('cadence_runtime', 'cadence_autostart', 'cadence_bridge'):
        sys.modules.pop(name, None)


def test_upgrade_reports_change_and_preserves_studio_files(connector):
    files = [connector / 'maya/scripts/userSetup.py', connector / 'maya/2022/Maya.env',
             connector / 'maya/modules/studio.mod']
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'studio-owned\r\n')
    assert install_connector('maya')
    assert not install_connector('maya')
    loader = connector / 'integrations/maya/scripts/userSetup.py'
    loader.write_text('import importlib.util\n', encoding='utf-8')
    assert install_connector('maya')
    assert not install_connector('maya')
    assert all(path.read_bytes() == b'studio-owned\r\n' for path in files)
    assert (connector / 'integrations/cadence_runtime.py').is_file()
    assert loader.read_text(encoding='utf-8').isascii()


@pytest.mark.parametrize('failure', ['missing', 'syntax', 'runtime', 'system_exit'])
def test_startup_failure_contained_before_other_scripts(connector, failure, caplog):
    install_connector('maya')
    module = connector / 'integrations/cadence_autostart.py'
    if failure == 'missing':
        module.unlink()
    else:
        module.write_text({'syntax': 'def invalid(:\n', 'runtime': "raise RuntimeError('test failure')\n",
                           'system_exit': 'raise SystemExit(1)\n'}[failure], encoding='utf-8')
    loader = connector / 'integrations/maya/scripts/userSetup.py'
    before = list(sys.path)
    namespace = {}
    exec(compile(loader.read_text(encoding='utf-8') + '\nstudio_started = True\n', str(loader), 'exec'), namespace)
    assert namespace['studio_started'] and sys.path == before
    assert 'cadence_autostart' not in sys.modules
    assert any('other startup scripts are unaffected' in record.message for record in caplog.records)


def test_faulty_studio_logging_handler_cannot_break_startup(connector, monkeypatch):
    install_connector('maya')
    (connector / 'integrations/cadence_autostart.py').unlink()
    def broken_logger(*args):
        raise RuntimeError('studio logging handler failed')
    monkeypatch.setattr(logging.getLogger('cadence.connector'), 'exception', broken_logger)
    loader = connector / 'integrations/maya/scripts/userSetup.py'
    namespace = {}
    exec(loader.read_text(encoding='utf-8') + '\nstudio_started = True\n', namespace)
    assert namespace['studio_started']


def test_failed_module_reload_restores_previous_module(tmp_path, monkeypatch):
    previous = ModuleType('cadence_test_reload')
    previous.value = 'previous'
    monkeypatch.setitem(sys.modules, previous.__name__, previous)
    module = tmp_path / 'broken.py'
    module.write_text("value = 'partial'\nraise RuntimeError('test failure')\n")
    with pytest.raises(RuntimeError):
        load_source(previous.__name__, module)
    assert sys.modules[previous.__name__] is previous and previous.value == 'previous'


def test_module_update_ignores_stale_bytecode(tmp_path, monkeypatch):
    module = tmp_path / 'updated.py'
    module.write_text("value = 'older'\n")
    timestamp = module.stat().st_mtime
    py_compile.compile(str(module), doraise=True)
    module.write_text("value = 'newer'\n")
    os.utime(module, (timestamp, timestamp))
    monkeypatch.delitem(sys.modules, 'cadence_test_updated', raising=False)
    assert load_source('cadence_test_updated', module).value == 'newer'
    sys.modules.pop('cadence_test_updated', None)


def test_deferred_start_failure_cleans_up_and_can_retry(monkeypatch):
    from integrations import cadence_autostart as auto
    from PySide6.QtCore import QTimer
    auto.shutdown()
    def fail():
        raise RuntimeError('timer unavailable')
    monkeypatch.setattr(auto, 'maya_timer', fail)
    auto.safe_start('maya')
    assert auto._monitor is None
    monkeypatch.setattr(auto, 'maya_timer', QTimer)
    monkeypatch.setattr(auto.Monitor, 'tick', lambda self: 1.)
    auto.safe_start('maya')
    assert auto._monitor is not None and auto._monitor.timer.isActive()
    auto.shutdown()


def test_blender_startup_uses_python3_loader(connector, monkeypatch):
    install_connector('blender')
    calls = []
    fake = ModuleType('cadence_autostart')
    fake.safe_start = lambda host: calls.append(host)
    fake.shutdown = lambda: calls.append('stop')
    monkeypatch.setitem(sys.modules, 'cadence_autostart', fake)
    loader = connector / 'blender/startup/cadence_timeline_startup.py'
    namespace = {}
    exec(loader.read_text(encoding='utf-8'), namespace)
    namespace['register']()
    namespace['unregister']()
    assert calls == ['blender', 'stop']


def test_maya_2022_selects_available_drawing_format(application, monkeypatch, tmp_path):
    from sync3d import TimelineLink
    from sync3d_dialog import SyncDialog
    from test_sync1120 import Window
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = Window()
    link = TimelineLink(window)
    link.host = 'maya'
    dialog = SyncDialog(link, window)
    assert dialog.drawing_mode.currentData() == 'blue_pencil'
    link.read_drawing(dict(type='capabilities', drawings=1, drawing_remove=1, drawing_modes=['images']))
    dialog.refresh()
    assert dialog.drawing_mode.count() == 1 and dialog.drawing_mode.currentData() == 'images'
    link.read_drawing(dict(type='capabilities', drawings=1, drawing_remove=1, drawing_modes=['grease_pencil','images']))
    dialog.refresh()
    assert dialog.drawing_mode.count() == 2
    assert dialog.drawing_mode.findData('grease_pencil') == 0
    link.stop()
    dialog.close()
    window.deleteLater()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows junction validation')
def test_drawing_bundle_rejects_junction_escape(tmp_path):
    import _winapi
    from integrations.cadence_drawings import load_bundle
    root = tmp_path / 'transfers'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (outside / 'manifest.json').write_text('{}')
    junction = root / 'linked'
    _winapi.CreateJunction(str(outside), str(junction))
    try:
        with pytest.raises(ValueError, match='outside'):
            load_bundle(junction / 'manifest.json', root)
    finally:
        junction.rmdir()
    assert (outside / 'manifest.json').is_file()
