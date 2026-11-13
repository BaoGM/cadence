# SPDX-License-Identifier: GPL-3.0-only
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, QUrl, QStandardPaths
from PySide6.QtWidgets import QApplication, QFileDialog, QListView, QComboBox, QDialogButtonBox, QPlainTextEdit
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtTest import QTest
import shiboken6

from test_sync1120 import application, Window, pump
from sync3d import TimelineLink
from sync3d_setup import install_connector


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'preferences.json'))
    monkeypatch.setenv('CADENCE_SYNC_ENDPOINT', str(tmp_path / 'endpoint.json'))
    monkeypatch.setenv('BLENDER_USER_SCRIPTS', str(tmp_path / 'blender-scripts'))
    monkeypatch.setenv('MAYA_APP_DIR', str(tmp_path / 'maya'))
    return tmp_path


def test_sidebar_receiver_destroyed_with_view(application, monkeypatch):
    from file_dialogs import SidebarLabels
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args))
    model = QStandardItemModel()
    desktop = QUrl.fromLocalFile(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation))
    item = QStandardItem('Desktop'); item.setData(desktop, Qt.UserRole + 1); model.appendRow(item)
    view = QListView(); view.setModel(model)
    labels = SidebarLabels(view)
    assert item.text() == 'Bureau'
    shiboken6.delete(view)
    assert not shiboken6.isValid(labels)
    item.setText('Desktop'); model.modelReset.emit()
    application.processEvents()
    assert item.text() == 'Desktop' and not errors


def test_repeated_open_save_export_dialogs(application, isolated, monkeypatch):
    from file_dialogs import install_file_places
    from ui_text import tr
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args))
    install_file_places()
    for number in range(30):
        dialog = QFileDialog(None, 'Test', str(isolated))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if number % 2 else QFileDialog.AcceptMode.AcceptOpen)
        dialog.setNameFilters(['Media (*.mp4)', 'Audio (*.wav)'])
        dialog.show(); application.processEvents()
        assert dialog.labelText(QFileDialog.DialogLabel.FileType) == tr('Type de fichier :')
        dialog.setDirectory(str(isolated.parent)); application.processEvents()
        dialog.selectNameFilter('Audio (*.wav)')
        dialog.reject(); dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()
    assert not errors


def test_host_choice_is_required_and_not_persisted(application, isolated, monkeypatch):
    (isolated / 'sync3d.json').write_text(json.dumps(dict(host='maya', offset=4, direction='receive')))
    window = Window(); link = TimelineLink(window)
    assert link.host is None and link.offset == 4
    choices = []
    link.choose_host = lambda: choices.append(True) or None
    link.prepare_connector = lambda: False
    link.set_enabled(True)
    assert not link.enabled and len(choices) == 1 and not (isolated / 'endpoint.json').exists()
    link.choose_host = lambda: choices.append(True) or 'maya'
    link.set_enabled(True)
    assert link.enabled and link.host == 'maya'
    link.stop(); link.set_enabled(True)
    assert len(choices) == 2
    link.save()
    assert 'host' not in json.loads((isolated / 'sync3d.json').read_text())
    other = TimelineLink(window)
    assert other.host is None
    link.stop(); window.deleteLater()


def test_host_dialog_no_default_and_cancel(application, monkeypatch):
    monkeypatch.setattr('sync3d_dialog.WINDOWS', True)
    from sync3d_dialog import choose_host
    def choose():
        dialog = application.activeModalWidget()
        combo = dialog.findChild(QComboBox); box = dialog.findChild(QDialogButtonBox)
        assert combo.currentData() is None and not box.button(QDialogButtonBox.Ok).isEnabled()
        combo.setCurrentIndex(2); box.button(QDialogButtonBox.Ok).click()
    QTimer.singleShot(0, choose)
    assert choose_host(None) == 'maya'
    QTimer.singleShot(0, lambda: application.activeModalWidget().reject())
    assert choose_host(None) is None


def test_setup_idempotent_and_existing_startup_preserved(application, isolated, monkeypatch):
    monkeypatch.setattr('sync3d_setup.WINDOWS', True)
    startup = isolated / 'maya/scripts/userSetup.py'
    startup.parent.mkdir(parents=True); startup.write_text('my_existing_setup = True\n')
    assert install_connector('maya')
    assert not install_connector('maya')
    assert startup.read_text() == 'my_existing_setup = True\n'
    assert (isolated / 'maya/modules/cadence_timeline.mod').is_file()
    assert install_connector('blender')
    assert not install_connector('blender')
    assert (isolated / 'blender-scripts/startup/cadence_timeline_startup.py').is_file()
    for name in ('cadence_bridge.py', 'cadence_autostart.py'):
        assert (isolated / 'integrations' / name).read_text(encoding='utf-8') == (Path(__file__).resolve().parents[1] / 'integrations' / name).read_text(encoding='utf-8')


def test_startup_monitor_stops_when_disabled_or_owner_exits(isolated, monkeypatch):
    from integrations import cadence_autostart as auto
    stopped = []
    monitor = auto.Monitor('blender')
    monitor.module = SimpleNamespace(stop=lambda: stopped.append(True)); monitor.token = 'a' * 64
    assert monitor.tick() == 1. and stopped == [True] and monitor.module is None
    (isolated / 'endpoint.json').write_text(json.dumps(dict(version=1, host='blender', token='a' * 64, pid=os.getpid())))
    monkeypatch.setattr(auto, 'owner_alive', lambda pid: False)
    assert monitor.tick() == 1. and monitor.module is None
    assert auto.owner_alive(-1) is False


def test_compact_dialog_has_no_script_controls(application, isolated):
    from sync3d_dialog import SyncDialog
    window = Window(); link = TimelineLink(window)
    dialog = SyncDialog(link, window)
    dialog.show(); application.processEvents()
    assert dialog.host.currentData() is None
    assert not dialog.findChildren(QPlainTextEdit)
    assert dialog.height() < 750
    dialog.close(); window.deleteLater()
