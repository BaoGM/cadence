# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from test_drawing import application, window


@pytest.mark.parametrize('tool', ['brush', 'arrow', 'rectangle', 'ellipse', 'text', 'eraser'])
def test_control_temporarily_picks_without_editing(window, tool):
    w=window; v=w.viewer; d=w.drawing
    v.resize(640,360); v.set_frame(np.full((360,640,3),[31,95,172],np.uint8))
    w.doc.state=replace(w.doc.state,selection=None)
    d.choose_tool(tool); v.cursor_guard.boundary(False)
    before=w.doc.state
    press=QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Control,Qt.KeyboardModifier.ControlModifier)
    v.cursor_guard.eventFilter(v,press)
    assert d.temporary_picker and v.cursor().shape()==Qt.CursorShape.BitmapCursor
    QTest.mouseClick(v,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,QPoint(320,180))
    assert d.wheel.color()=='#1f5fac' and w.doc.state is before
    assert d.tool.currentData()==tool and not d.sampling and d.stroke is None and d.text_drag is None
    release=QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Control,Qt.KeyboardModifier.ControlModifier)
    v.cursor_guard.eventFilter(v,release)
    assert not d.temporary_picker and v.cursor_guard.desired.shape()==Qt.CursorShape.CrossCursor


def test_control_during_shape_preserves_center_constraint(window):
    w=window; v=w.viewer; d=w.drawing
    v.resize(640,360); v.set_frame(np.zeros((360,640,3),np.uint8))
    d.choose_tool('rectangle'); d.begin(QPointF(320,180),1.)
    d.move(QPointF(360,220),1.,Qt.KeyboardModifier.ControlModifier)
    d.update_picker_cursor(Qt.KeyboardModifier.ControlModifier)
    assert not d.temporary_picker and d.shape_drag is not None
    a,b=d.stroke.points
    assert a[:2]==pytest.approx((280/640,140/360))
    assert b[:2]==pytest.approx((360/640,220/360))
    d.cancel()


def test_picker_cursor_does_not_escape_video(window):
    v=window.viewer; d=window.drawing
    v.set_frame(np.zeros((60,100,3),np.uint8)); d.choose_tool('brush')
    v.cursor_guard.boundary(False); d.update_picker_cursor(Qt.KeyboardModifier.ControlModifier)
    v.cursor_guard.boundary(True)
    assert v.cursor().shape()==Qt.CursorShape.ArrowCursor
    v.cursor_guard.release()
    assert not d.temporary_picker and not d.sampling
