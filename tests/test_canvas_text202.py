# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest

from test_drawing import application, screen_point, window


def draw_box(w):
    w.request_frame=lambda:None
    d=w.drawing
    d.choose_tool('text')
    start=screen_point(d,.15,.2).toPoint()
    end=screen_point(d,.7,.64).toPoint()
    QTest.mousePress(w.viewer,Qt.LeftButton,pos=start)
    QTest.mouseMove(w.viewer,end)
    QTest.mouseRelease(w.viewer,Qt.LeftButton,pos=end)
    assert d.text_editor is not None
    return d.text_editor


def test_canvas_ime_shortcuts_focus_and_undo(window,application):
    w=window
    editor=draw_box(w)
    assert application.focusWidget() is editor and not application.activeModalWidget()
    QTest.keyClicks(editor,'B D ')
    assert editor.toPlainText()=='B D ' and w.drawing.tool.currentData()=='text'
    event=QInputMethodEvent()
    event.setCommitString('été 🎨')
    application.sendEvent(editor,event)
    assert editor.toPlainText()=='B D été 🎨'
    QTest.keyClick(editor,Qt.Key_Z,Qt.ControlModifier)
    assert editor.toPlainText()=='B D ' and not w.doc.undo_stack
    editor.insertPlainText('direction')
    w.drawing.hex.setFocus(Qt.OtherFocusReason)
    assert w.drawing.text_editor is None and w.doc.state.drawings[0].marks[0].text=='B D direction'
    assert len(w.doc.undo_stack)==1
    w.doc.undo()
    assert not w.doc.state.drawings
    w.doc.redo()
    assert w.doc.state.drawings[0].marks[0].text=='B D direction'


@pytest.fixture
def studio_style(application):
    from app import STYLE
    previous_sheet=application.styleSheet()
    application.setStyleSheet('')
    previous_style=application.style().name()
    application.setStyle('Fusion')
    application.setStyleSheet(STYLE)
    yield
    application.setStyleSheet('')
    application.setStyle(previous_style)
    application.setStyleSheet(previous_sheet)


def test_canvas_existing_cancel_click_and_transformed_hit(studio_style,window,application):
    w=window; d=w.drawing; v=w.viewer
    editor=draw_box(w)
    QTest.keyClicks(editor,'first')
    QTest.keyClick(editor,Qt.Key_Return)
    original=w.doc.state.drawings
    QTest.mouseDClick(v,Qt.LeftButton,pos=screen_point(d,.34,.36).toPoint())
    editor=d.text_editor
    assert editor and editor.toPlainText()=='first'
    QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
    QTest.keyClicks(editor,'New')
    QTest.keyClick(editor,Qt.Key_Escape)
    assert d.text_editor is None and w.doc.state.drawings is original and len(w.doc.undo_stack)==1

    v.zoom=1.25; v.angle=17; v.pan=QPointF(9,11)
    QTest.mouseDClick(v,Qt.LeftButton,pos=screen_point(d,.34,.36).toPoint())
    editor=d.text_editor
    assert editor.document_point(screen_point(d,.15,.20)).toTuple()==pytest.approx((0,0),abs=4.)
    QTest.mouseClick(v,Qt.LeftButton,pos=screen_point(d,.16,.22).toPoint())
    assert d.text_editor is editor and editor.textCursor().position()<=1
    editor.moveCursor(QTextCursor.End)
    QTest.keyClicks(editor,' take')
    QTest.mouseClick(v,Qt.LeftButton,pos=screen_point(d,.9,.65).toPoint())
    assert d.text_editor is None and w.doc.state.drawings[0].marks[0].text=='first take'
    assert len(w.doc.undo_stack)==2


def test_canvas_stale_draft_and_blank_do_not_edit_project(window):
    w=window; d=w.drawing
    editor=draw_box(w)
    QTest.keyClick(editor,Qt.Key_Return)
    assert not w.doc.state.drawings and not w.doc.undo_stack
    editor=draw_box(w)
    QTest.keyClicks(editor,'ignore')
    from drawing import DrawingKey
    other=(DrawingKey(7,9,()),)
    w.doc.state=replace(w.doc.state,drawings=other)
    w.refresh()
    assert d.text_editor is None and w.doc.state.drawings is other and not w.doc.undo_stack
