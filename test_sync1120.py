# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import socket
import select
import time
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QFileDialog, QMessageBox
from PySide6.QtTest import QTest

from model import Document, State, Segment
from sync3d import TimelineLink, frame_rate, to_cadence, to_host, state_message
from integrations.cadence_bridge import Bridge


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


def pump(application, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate(): return
        QTest.qWait(5)
    raise AssertionError('Synchronization timed out')


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.doc.fps = Fraction(24)
        self.doc.state = State((Segment(None, 0, 300),), selection=(10, 40))
        self.job = None
        self.errors = []
        self.seeks = []

    def error(self, text): self.errors.append(text)

    def seek(self, frame):
        self.seeks.append(frame)
        self.doc.state = replace(self.doc.state, position=frame)


@pytest.fixture
def link(application, tmp_path, monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.setenv('CADENCE_SYNC_ENDPOINT', str(tmp_path / 'endpoint.json'))
    window = Window()
    link = TimelineLink(window)
    link.host = 'blender'
    link.prepare_connector = lambda: False
    link.set_enabled(True)
    assert link.enabled and not window.errors
    yield link
    link.stop()
    window.deleteLater()
    application.processEvents()
    assert not (tmp_path / 'endpoint.json').exists()


def test_mapping_fractional_rates_negative_origin_and_offset():
    fps = frame_rate(23.976)
    assert fps == Fraction(24000, 1001)
    assert to_cadence(1031, 1001, Fraction(30), Fraction(24), 4) == 28
    assert to_host(28, 1001, Fraction(30), Fraction(24), 4) == 1031
    assert to_cadence(-11, -23, Fraction(24), Fraction(24), -5) == 7
    for frame in range(0, 10000, 17):
        host = to_host(frame, -1001, fps, Fraction(24), 7)
        assert to_cadence(host, -1001, fps, Fraction(24), 7) == frame


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '24', 0, 10000])
def test_reject_bad_rates(value):
    with pytest.raises((ValueError, TypeError)):
        frame_rate(value)


def test_bidirectional_reconnect_offset_and_no_echo(link, application):
    host = dict(frame=101., start=101., end=500., fps=30.)
    applied = []
    def set_frame(frame):
        applied.append(frame)
        host['frame'] = frame
    bridge = Bridge('blender', lambda: dict(host), set_frame)
    def wait(predicate):
        pump(application, lambda: (bridge.tick(), predicate())[1])
    try:
        wait(lambda: link.metadata is not None)
        wait(lambda: link.window.doc.state.position == 0)
        host['frame'] = 131
        wait(lambda: link.window.doc.state.position == 24)
        assert link.window.doc.state.selection == (10, 40)
        link.window.seek(48)
        wait(lambda: host['frame'] == 161)
        assert applied == [161]
        for _ in range(30):
            bridge.tick(); application.processEvents(); QTest.qWait(3)
        assert applied == [161]
        link.configure('blender', 'receive', 5, True)
        wait(lambda: link.window.doc.state.position == 53)
        link.window.seek(80)
        for _ in range(20):
            bridge.tick(); application.processEvents(); QTest.qWait(3)
        assert host['frame'] == 161
        link.configure('blender', 'receive', 32, True)
        assert link.offset == 32
        link.stop()
        wait(lambda: bridge.sock is None)
        assert not link.timer.isActive()
        link.set_enabled(True)
        bridge = Bridge('blender', lambda: dict(host), set_frame)
        wait(lambda: link.metadata is not None)
    finally:
        bridge.close()


def test_reject_unauthorized_and_malformed_packets(link, application):
    def connect(payload):
        sock = socket.create_connection(('127.0.0.1', link.server.serverPort()), timeout=1)
        pump(application, lambda: link.peer is not None)
        sock.sendall(payload)
        pump(application, lambda: link.peer is None)
        sock.close()
    connect(b'{"type":"hello","version":1,"host":"blender","token":"wrong"}\n')
    hello = dict(type='hello', version=1, host='blender', token=link.token)
    connect((json.dumps(hello) + '\n' + json.dumps(dict(type='state', frame=float('nan'), fps=24, start=0, end=100)) + '\n').encode())
    connect(b'x' * 16385)
    assert not link.window.seeks


def test_endpoint_lock_does_not_break_first_instance(link, application):
    other_window = Window()
    other = TimelineLink(other_window)
    other.host = 'blender'
    other.prepare_connector = lambda: False
    other.set_enabled(True)
    assert not other.enabled and other_window.errors
    assert link.enabled
    other.stop()
    other_window.deleteLater()


def test_slow_host_keeps_one_frame_in_flight(link, application):
    link.direction = 'send'
    sock = socket.create_connection(('127.0.0.1', link.server.serverPort()), timeout=1)
    sock.setblocking(False)
    try:
        hello = dict(type='hello', version=1, host='blender', token=link.token)
        state = dict(type='state', frame=1, start=1, end=300, fps=24)
        sock.sendall((json.dumps(hello) + '\n' + json.dumps(state) + '\n').encode())
        pump(application, lambda: link.awaiting is not None)
        sequence = link.awaiting
        for frame in range(1, 200):
            link.window.seek(frame); link.tick(); application.processEvents()
        assert link.awaiting == sequence
        packets = sock.recv(16384).splitlines()
        commands = [json.loads(packet) for packet in packets if json.loads(packet)['type'] == 'frame']
        assert len(commands) == 1
        sock.sendall((json.dumps(dict(state, type='ack', seq=sequence)) + '\n').encode())
        pump(application, lambda: link.awaiting is not None and link.awaiting != sequence)
        pump(application, lambda: bool(select.select([sock], [], [], 0)[0]))
        packets = sock.recv(16384).splitlines()
        commands = [json.loads(packet) for packet in packets if json.loads(packet)['type'] == 'frame']
        assert len(commands) == 1 and commands[0]['frame'] == 200
    finally:
        sock.close()


def test_save_shortcut_migration_preserves_custom_binding(application):
    from preferences import defaults, validate
    registry = {'Fichier/Enregistrer': (None, 'Ctrl+S'),
                'Fichier/Enregistrer sous…': (None, 'Ctrl+Shift+S')}
    data = defaults(registry)
    data['shortcuts'] = {'Fichier/Enregistrer le projet': 'Ctrl+Alt+F2'}
    assert validate(data, registry)['shortcuts']['Fichier/Enregistrer'] == 'Ctrl+Alt+F2'


def test_rate_offer_once_and_explicit_accept(link, application, monkeypatch):
    w = link.window
    w.doc.media = {'m': dict(id='m', fps='24', original_fps='24', has_video=True)}
    w.doc.state = State((Segment('m', 0, 300),))
    link.metadata = dict(frame=1, start=1, end=300, fps=Fraction(30))
    questions, changes = [], []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: questions.append(args) or QMessageBox.StandardButton.No)
    monkeypatch.setattr(link, 'adapt_media', lambda *args: changes.append(args))
    link.check_rate()
    pump(application, lambda: not link.prompt_open)
    link.check_rate(); application.processEvents()
    assert len(questions) == 1 and not changes
    link.metadata['fps'] = Fraction(12)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    link.check_rate()
    pump(application, lambda: not link.prompt_open)
    assert changes == [(w.doc, 'm', Fraction(12))]


def test_media_adaptation_preserves_duration_and_undo(link):
    from media import prepare_media
    w = link.window
    media = prepare_media(Path(__file__).parent / 'assets' / 'Demonstration.mp4', quality='480p')
    w.doc = Document(); w.doc.append_media([media]); baseline = w.doc.state
    original_fps = w.doc.fps
    w.preferences = {'preview_quality': '480p'}
    w.pause = w.commit_exposure = w.refresh = w.request_frame = lambda: None
    w.drawing = SimpleNamespace(finish=lambda: None)
    w.begin_task = lambda title, prepare, apply: apply(prepare(lambda *args: None, threading.Event()))
    link.adapt_media(w.doc, media['id'], Fraction(30))
    changed = w.doc.state
    assert changed.length == baseline.length and w.doc.fps == original_fps
    converted = w.doc.media[changed.segments[0].media]
    assert converted['cadence']['rate'] == '30' and converted['cadence']['speed'] == '1'
    assert converted['path'] == media['path']
    w.doc.undo(); assert w.doc.state == baseline
    w.doc.redo(); assert w.doc.state == changed


def test_capture_cursor_method_and_dialog_labels(application, tmp_path, monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    from capture import CaptureDialog
    from file_dialogs import install_file_places
    from ui_text import tr
    parent = QWidget()
    capture = CaptureDialog(parent)
    try:
        assert callable(capture.cursor)
        assert capture.include_cursor.isChecked()
        capture.show(); application.processEvents()
        assert capture.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        capture.reject(); capture.deleteLater(); parent.deleteLater()
    install_file_places()
    dialog = QFileDialog()
    dialog.show(); application.processEvents()
    for role, text in ((QFileDialog.DialogLabel.LookIn, 'Dossier :'),
                       (QFileDialog.DialogLabel.FileName, 'Nom de fichier :'),
                       (QFileDialog.DialogLabel.FileType, 'Type de fichier :')):
        assert dialog.labelText(role) == tr(text)
        assert '&' not in dialog.labelText(role)
    dialog.reject(); dialog.deleteLater(); application.processEvents()
