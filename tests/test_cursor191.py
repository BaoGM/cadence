# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget
from test_d3d160 import application


@pytest.fixture
def window(application, monkeypatch):
    monkeypatch.setenv('CADENCE_RENDERER', 'software')
    from widgets import Viewer
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    host.resize(700, 400)
    viewer = Viewer()
    viewer.setParent(host)
    viewer.setGeometry(0, 0, 500, 300)
    panel = QWidget(host)
    panel.setGeometry(500, 0, 200, 400)
    host.show()
    application.processEvents()
    try:
        yield host, viewer, panel
    finally:
        host.close()
        host.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()


def native_message(guard, hit, monkeypatch, message=0x0020, area=1, event_type=b'windows_generic_MSG'):
    monkeypatch.setattr(QApplication, 'widgetAt', staticmethod(lambda pos: hit))
    msg = wintypes.MSG()
    msg.message = message
    msg.lParam = area
    return guard.native.nativeEventFilter(event_type, ctypes.addressof(msg))


def test_native_message_repairs_stale_windows_cursor(window, monkeypatch):
    host, viewer, panel = window
    guard = viewer.cursor_guard
    native = guard.native
    user32 = native.user32
    user32.GetCursor.argtypes = []
    user32.GetCursor.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    monkeypatch.setattr(QApplication, 'widgetAt', staticmethod(lambda pos: panel))
    guard.boundary(True)
    assert viewer.cursor().shape() == Qt.CursorShape.ArrowCursor
    wrong = user32.LoadCursorW(None, 32649)
    previous = user32.SetCursor(wrong)
    try:
        assert user32.GetCursor() == wrong
        hwnd = int(host.winId())
        assert user32.SendMessageW(hwnd, 0x0020, hwnd, 1) == 1
        assert user32.GetCursor() == native.arrow
        guard.boundary(False)
        viewer.setCursor(Qt.CursorShape.ClosedHandCursor)
        assert user32.SendMessageW(hwnd, 0x0020, hwnd, 1) == 1
        assert guard.outside and user32.GetCursor() == native.arrow
    finally:
        user32.SetCursor(previous)


@pytest.mark.parametrize('target', ['viewer', 'video_child', 'text', 'resize', 'foreign', 'none'])
def test_native_boundary_preserves_other_cursors(window, monkeypatch, target):
    host, viewer, panel = window
    guard = viewer.cursor_guard
    guard.boundary(False)
    foreign = QWidget()
    targets = {'viewer': viewer, 'video_child': QWidget(viewer), 'text': QLineEdit(panel),
               'resize': QWidget(panel), 'foreign': foreign, 'none': None}
    targets['text'].setCursor(Qt.CursorShape.IBeamCursor)
    targets['resize'].setCursor(Qt.CursorShape.SizeHorCursor)
    try:
        assert native_message(guard, targets[target], monkeypatch) == (False, 0)
        assert not guard.outside
    finally:
        foreign.deleteLater()


@pytest.mark.parametrize('message,area,event_type', [(0x0200, 1, b'windows_generic_MSG'),
    (0x0020, 10, b'windows_generic_MSG'), (0x0020, 1, b'windows_dispatcher_MSG')])
def test_native_boundary_ignores_nonclient_and_unrelated_messages(window, monkeypatch, message, area, event_type):
    _, viewer, panel = window
    assert native_message(viewer.cursor_guard, panel, monkeypatch, message, area, event_type) == (False, 0)


def test_native_boundary_preserves_busy_override(window, monkeypatch, application):
    _, viewer, panel = window
    application.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        assert native_message(viewer.cursor_guard, panel, monkeypatch) == (False, 0)
        assert application.overrideCursor().shape() == Qt.CursorShape.WaitCursor
    finally:
        application.restoreOverrideCursor()


@pytest.mark.parametrize('parent_is_viewer', [False, True])
def test_dialog_over_video_is_outside_and_release_ends_drag(window, parent_is_viewer):
    host, viewer, _ = window
    guard = viewer.cursor_guard
    dialog = QDialog(viewer if parent_is_viewer else host)
    guard.boundary(False)
    viewer.setCursor(Qt.CursorShape.ClosedHandCursor)
    global_pos = QPointF(viewer.mapToGlobal(viewer.rect().center()))
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(10, 10), global_pos,
                      Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    guard.eventFilter(dialog, move)
    assert guard.outside and viewer.cursor().shape() == Qt.CursorShape.ArrowCursor
    dialog.deleteLater()
    from drag import ContinuousDrag
    viewer.origin = QPointF(10, 10)
    viewer._video_drag = ContinuousDrag(global_pos)
    releases = []
    viewer.scrubActiveChanged.connect(releases.append)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(10, 10), global_pos,
                         Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    guard.eventFilter(host, release)
    assert viewer.origin is None and releases == [False]


def test_boundary_survives_hide_show_and_viewer_deletion(window, application, monkeypatch):
    host, viewer, panel = window
    guard = viewer.cursor_guard
    native = guard.native
    viewer.hide()
    application.processEvents()
    assert not guard.active
    assert native_message(guard, panel, monkeypatch) == (True, 1)
    viewer.show()
    application.processEvents()
    assert guard.active and guard.native is native
    viewer.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    from shiboken6 import isValid
    assert not isValid(viewer)
    errors = []
    monkeypatch.setattr('sys.excepthook', lambda *error: errors.append(error))
    native.user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    native.user32.SendMessageW.restype = wintypes.LPARAM
    hwnd = int(host.winId())
    native.user32.SendMessageW(hwnd, 0x0020, hwnd, 1)
    assert errors == []
