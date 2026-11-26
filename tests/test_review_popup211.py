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


def test_popup_fifteen_lines_then_scroll_and_keep_boxes_out_of_copy(window,application):
    from PySide6.QtCore import QRect,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from marker_popup import MarkerPopup
    view=MarkerPopup(window.timeline)
    anchor=QRect(window.screen().availableGeometry().center(),window.size()/20)
    try:
        lines=['☐ Pose']+['Suite']*14
        view.present('\n'.join(lines),anchor)
        application.processEvents()
        assert not view.verticalScrollBar().isVisible() and view.verticalScrollBar().maximum()==0
        view.present('\n'.join(lines+['☑ Fin']),anchor)
        application.processEvents()
        assert view.verticalScrollBar().isVisible() and view.verticalScrollBar().maximum()>0
        assert view.cursorRect(QTextCursor(view.document().findBlockByNumber(14))).bottom()<view.viewport().height()
        cursor=QTextCursor(view.document())
        left=view.cursorRect(cursor).center()
        cursor.movePosition(QTextCursor.NextCharacter)
        box=(left+view.cursorRect(cursor).center())/2
        application.sendEvent(view.viewport(),QMouseEvent(QEvent.MouseMove,QPointF(box),QPointF(view.viewport().mapToGlobal(box)),Qt.NoButton,Qt.NoButton,Qt.NoModifier))
        assert view.viewport().cursor().shape()==Qt.PointingHandCursor
        before=view.viewport().grab().toImage()
        view.selectAll()
        application.processEvents()
        selected=view.viewport().grab().toImage()
        assert before.pixelColor(box)==selected.pixelColor(box)
        assert view.createMimeDataFromSelection().text()=='\n'.join(lines+['☑ Fin']).replace('☐','').replace('☑','')
    finally:
        view.close()


def test_comment_row_wraps_to_two_lines_and_renames_without_seeking(window,application,monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QInputDialog
    window.request_frame=lambda:None
    panel=opened_comments(window,application)
    window.seek(7)
    window.doc.set_marker_note(2,1,'A')
    window.doc.rename_marker(2,'Un titre de marqueur assez long pour apparaître sur une deuxième ligne du panneau')
    window.refresh(); application.processEvents()
    items=panel.items
    rect=items.visualItemRect(items.item(0))
    assert items.fontMetrics().height()*1.5<=rect.height()<=items.fontMetrics().lineSpacing()*2+6
    image=items.viewport().grab().toImage()
    scale=image.devicePixelRatio()
    for top,bottom in [(rect.top()+3,rect.center().y()),(rect.center().y()+2,rect.bottom()-2)]:
        colors={image.pixelColor(x,y).rgb()
                for y in range(round(top*scale),round(bottom*scale))
                for x in range(round((rect.left()+50)*scale),round((rect.right()-6)*scale))}
        assert len(colors)>4, 'Le titre doit être dessiné sur chacune des deux lignes.'
    icon_colors={image.pixelColor(x,y).rgb()
                 for y in range(round((rect.center().y()-8)*scale),round((rect.center().y()+8)*scale))
                 for x in range(round((rect.left()+5)*scale),round((rect.left()+21)*scale))}
    assert len(icon_colors)>4
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**kw:('Pose finale',True))
    def choose_rename():
        menu=QApplication.activePopupWidget()
        action=next(a for a in menu.actions() if a.text()=='Renommer le marqueur…')
        QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center())
    QTimer.singleShot(30,choose_rename)
    panel.marker_menu(rect.center())
    assert window.doc.state.marker_names==((2,'Pose finale'),) and window.doc.state.position==7


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
