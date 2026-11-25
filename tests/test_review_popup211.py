# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from model import Document
from test_drawing import application, window
from test_review_comments import opened_comments
from timeline_skin import marker_areas


def test_comments_follow_range_without_overwriting_a_marker_or_draft(window,application):
    panel=opened_comments(window,application)
    w=window
    panel.set_range_mode(False)
    w.doc.set_marker_note(2,2,'Old')
    w.seek(4)
    panel.text.setPlainText('New')
    w.select(8,16,position=2)
    assert panel.frame is None and panel.text.toPlainText()=='New'
    assert panel.range_stack.currentWidget() is panel.ranges and panel.ranges.text()=='8-15'
    assert w.doc.state.marker_notes==((2,2,'Old'),)
    panel.ranges.setFocus()
    QTest.keyClick(panel.ranges,Qt.Key_Return)
    assert w.doc.state.marker_notes==((2,2,'Old'),(8,8,'New'))
    w.clear_selection()
    w.seek(4)
    w.doc.state=replace(w.doc.state,selection=(0,5),selected_clips=(('a',0,5),('a',12,18)))
    w.refresh()
    assert panel.ranges.text()=='0-4, 12-17'
    panel.items.setCurrentItem(panel.items.item(0))
    assert panel.frame==2 and panel.text.toPlainText()=='Old'
    w.clear_selection()
    assert panel.range_stack.currentWidget() is panel.duration


def test_reopening_after_copy_has_no_inherited_formatting(application):
    from review_editor import ReviewEditor,ITALIC
    edit=ReviewEditor()
    edit.load('First note',((0,10,ITALIC),))
    edit.selectAll()
    edit.load('☐ Pose',((2,6,1),))
    assert edit.style_runs()==((2,6,1),)
    edit.close()


@pytest.mark.parametrize('simple',(True,False))
def test_popup_rich_selection_copy_and_checkboxes(window,application,tmp_path,simple):
    w=window
    panel=opened_comments(w,application)
    w.workspaces.set_timeline_simple(simple)
    w.seek(6)
    text='☐ Pose 👋\nRegard'
    runs=((2,6,3),(10,16,12))
    assert w.doc.set_marker_note(6,2,text,runs)
    w.refresh()
    t=w.timeline
    hover=t.marker_hover
    flag=next(flag for _,frame,flag,_ in marker_areas(t) if frame==6)
    hover.hover((6,''),flag.center())
    QTest.qWait(410)
    popup=hover.popup
    assert popup and popup.isVisible() and popup.isReadOnly()
    assert popup.style_runs()==runs
    def point(index):
        cursor=QTextCursor(popup.document())
        cursor.setPosition(index)
        return popup.cursorRect(cursor).center()
    QTest.mousePress(popup.viewport(),Qt.LeftButton,pos=point(2))
    QTest.mouseMove(popup.viewport(),point(6))
    QTest.mouseRelease(popup.viewport(),Qt.LeftButton,pos=point(6))
    assert popup.textCursor().selectedText()=='Pose'
    if application.platformName()=='offscreen':
        assert QApplication.focusWidget() is popup
        QTest.keyClick(QApplication.focusWidget(),Qt.Key_C,Qt.ControlModifier)
        assert QApplication.clipboard().text()=='Pose'
    before=len(w.doc.undo_stack)
    QTest.mouseClick(popup.viewport(),Qt.LeftButton,pos=(point(0)+point(1))/2)
    updated=text.replace('☐','☑')
    assert popup.isVisible() and popup.toPlainText()==updated
    assert panel.text.toPlainText()==updated and w.doc.state.position==6
    assert w.doc.state.marker_notes==((6,2,updated),) and popup.style_runs()==runs
    assert len(w.doc.undo_stack)==before+1
    path=tmp_path/'checked.cadence'
    w.doc.save(path)
    saved=Document.load(path).state
    assert saved.marker_notes==w.doc.state.marker_notes and saved.marker_styles==w.doc.state.marker_styles
    assert w.doc.undo()
    w.refresh()
    assert popup.toPlainText()==text and panel.text.toPlainText()==text
    hover.cancel()
