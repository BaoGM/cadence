# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication

from drawing import DrawingKey, Mark
from model import Document, Segment, State
from test_render1170 import application
from test_tools0160 import mouse
from widgets import Timeline


@pytest.mark.parametrize('simple', [False, True])
@pytest.mark.parametrize('operation', ['left', 'right', 'extend', 'move'])
def test_key_drag_preview_without_media_selection(application, simple, operation):
    doc = Document()
    key = DrawingKey(10, 11 if operation == 'extend' else 20, (Mark(),))
    doc.state = State((Segment(None, 0, 60),), drawings=(key,))
    timeline = Timeline(); timeline.simple = simple; timeline.resize(1000, 100)
    def refresh(): timeline.set_document(doc.state, {}, 24)
    timeline.selected.connect(lambda a, b: (doc.select(a, b), refresh()))
    timeline.drawingResized.connect(lambda *args: (doc.resize_drawing(*args), refresh()))
    timeline.drawingMoved.connect(lambda *args: (doc.move_drawings(*args), refresh()))
    refresh(); timeline.show(); application.processEvents()
    try:
        y = timeline.track_y('drawing') + 2
        start = 10 if operation == 'left' else 20 if operation == 'right' else 10 if operation == 'extend' else 15
        delta = -4 if operation == 'left' else 5
        modifiers = Qt.KeyboardModifier.AltModifier if operation == 'move' else Qt.KeyboardModifier.NoModifier
        point = QPointF(timeline.x_for(start), y)
        end = QPointF(timeline.x_for(start + delta), y)
        before = timeline.grab().toImage()
        original = doc.state
        mouse(timeline, QEvent.Type.MouseButtonPress, point, modifiers)
        assert doc.state.selection is None
        mouse(timeline, QEvent.Type.MouseMove, end, modifiers)
        assert doc.state == original and timeline.drawing_track.preview != original.drawings
        preview = timeline.grab().toImage()
        assert before.copy(0, y-3, before.width(), 7) != preview.copy(0, y-3, preview.width(), 7)
        mouse(timeline, QEvent.Type.MouseButtonRelease, end, modifiers)
        assert doc.state.selection is None and doc.state.drawings != original.drawings
        assert doc.state.segments == original.segments
        assert doc.undo() and doc.state == original
        assert doc.redo() and doc.state.drawings != original.drawings
    finally:
        timeline.close(); timeline.deleteLater(); application.processEvents()


@pytest.mark.parametrize('first', [False, True])
def test_empty_active_track_does_not_break_sync_rate_checks(application, tmp_path, monkeypatch, first):
    from test_sync1120 import Window
    from sync3d import TimelineLink
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = Window(); link = TimelineLink(window)
    window.doc.media = {'m': dict(id='m', fps='24', has_video=True)}
    window.doc.state = State((Segment('m', 0, 60),), position=40)
    window.doc.add_media_track()
    if first: window.doc.reorder_media_track(window.doc.active_track_id, -1)
    link.metadata = dict(frame=1, start=1, end=300, fps=Fraction(24))
    try:
        for _ in range(5): link.check_rate()
        link.adapt_current()
        assert not link.rate_decisions and not link.prompt_open
        from PySide6.QtWidgets import QMessageBox
        adapted = []
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(link, 'adapt_keys', lambda doc, keys, rate: adapted.append((keys, rate)))
        link.adapt_current(True)
        assert adapted == [({'m'}, Fraction(24))]
    finally:
        link.stop(); window.close(); window.deleteLater(); application.processEvents()


def test_mirror_has_only_video_and_hover_controls(application, tmp_path, monkeypatch):
    from app import MainWindow
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMenu
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = MainWindow(); window.show(); application.processEvents()
    menus = []
    def inspect_menu():
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            menus.append(list(menu.actions())); menu.close()
    try:
        point = window.viewer.rect().center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, window.viewer.mapToGlobal(point))
        QTimer.singleShot(30, inspect_menu)
        QApplication.sendEvent(window.viewer, event)
        assert any(window.video_mirror_action in actions for actions in menus)
        window.video_mirror_action.trigger(); application.processEvents()
        mirror = window.video_mirror
        assert mirror.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert mirror.canvas.geometry() == mirror.rect()
        mirror.canvas.setFocus(); mirror.update_controls(QPoint(100, 80))
        assert not mirror.controls.isVisible()
        mirror.update_controls(mirror.controls.geometry().center())
        assert mirror.controls.isVisible()
        mirror.on_top.click()
        assert mirror.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert mirror.windowFlags() & Qt.WindowType.FramelessWindowHint
        mirror.opacity.setValue(45)
        assert abs(mirror.windowOpacity()-.45) < .01
        mirror.update_controls(QPoint(100, 80))
        assert not mirror.controls.isVisible()
        mirror.resize(320, 180); application.processEvents()
        assert mirror.canvas.geometry() == mirror.rect()
        assert mirror.canvas.rect().contains(mirror.controls.geometry())
        original = mirror.geometry()
        mouse(mirror.canvas, QEvent.Type.MouseButtonPress, QPointF(100, 60))
        mouse(mirror.canvas, QEvent.Type.MouseMove, QPointF(140, 85))
        mouse(mirror.canvas, QEvent.Type.MouseButtonRelease, QPointF(140, 85))
        assert mirror.pos() == original.topLeft()+QPoint(40, 25)
        corner = QPointF(mirror.width()-2, mirror.height()-2)
        mouse(mirror.canvas, QEvent.Type.MouseButtonPress, corner)
        mouse(mirror.canvas, QEvent.Type.MouseMove, corner+QPointF(40, 30))
        mouse(mirror.canvas, QEvent.Type.MouseButtonRelease, corner+QPointF(40, 30))
        assert mirror.size().width() == original.width()+40 and mirror.size().height() == original.height()+30
        mirror.close_button.click()
        assert not mirror.isVisible() and not window.video_mirror_action.isChecked()
    finally:
        window.close(); application.processEvents()
