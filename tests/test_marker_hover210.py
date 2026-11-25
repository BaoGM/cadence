# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from model import Document, Segment, State
from preferences import defaults, validate
from test_drawing import window
from test_timeline200 import application, timeline
from timeline_skin import marker_areas


def test_timeline_selection_markers_preserve_existing_comment_and_undo():
    doc = Document()
    original = State((Segment(None,0,50),), position=38, selection=(4,30),
                     selected_clips=(('a',4,12),('a',12,20),('a',27,30)),
                     frame_markers=(4,), marker_names=((4,'Plan'),), marker_notes=((4,1,'Commentaire'),),
                     marker_styles=((4,((0,2,1),)),))
    doc.state = original
    assert doc.add_timeline_marker(toggle=True)
    assert doc.state.frame_markers == (4,27)
    assert doc.state.marker_notes == ((4,16,'Commentaire'),(27,3,''))
    assert doc.state.marker_styles == original.marker_styles and doc.state.marker_names == original.marker_names
    assert not doc.add_timeline_marker(38)
    assert doc.undo() and doc.state == original
    doc.state = replace(original, selection=None, selected_clips=(), position=4)
    assert not doc.add_timeline_marker()
    assert doc.add_timeline_marker(toggle=True) and not doc.state.frame_markers


def test_all_marker_commands_use_the_selected_range(window, application):
    w = window
    w.workspaces.set_timeline_simple(False)
    t = w.timeline
    w.doc.state = replace(w.doc.state, position=21, selection=(6,16))
    w.refresh()
    w.activateWindow()
    t.setFocus()
    application.processEvents()
    def check_and_undo():
        assert w.doc.state.frame_markers == (6,) and w.doc.state.marker_notes == ((6,10,''),)
        assert w.doc.undo()
        w.refresh()
    QTest.keyClick(t, Qt.Key_S)
    check_and_undo()
    QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, QPoint(t.track_left()-12,10))
    check_and_undo()
    menu = t.context_menu(QPoint(round(t.x_for(19)), t.track_y('video')+3))
    next(a for a in menu.actions() if a.data()=='add_marker').trigger()
    check_and_undo()
    w.drawing.comments.add.click()
    check_and_undo()


def test_comments_hover_scrolls_and_respects_own_preference(timeline):
    widget, doc = timeline
    widget.move(80,250)
    text = 'Storyboard & animation <revue>\n' + '\n'.join(
        f'{i} – vérifier la pose de contact et le regard.' for i in range(300))
    doc.state = replace(doc.state, marker_notes=((36,3,text),))
    widget.set_document(doc.state, doc.media, 24)
    app = QApplication.instance()
    from ui_style import set_tooltips_enabled
    set_tooltips_enabled(False)
    popup = widget.marker_hover
    assert defaults({})['marker_comments_hover'] and not defaults({})['tooltips']
    assert validate({'format':'cadence-shortcuts','version':1,'marker_comments_hover':False},{})['marker_comments_hover'] is False
    point = next(marker_areas(widget))[2].center().toPoint()
    def hover(where):
        app.sendEvent(widget, QMouseEvent(QEvent.MouseMove, QPointF(where), QPointF(widget.mapToGlobal(where)),
                                         Qt.NoButton,Qt.NoButton,Qt.NoModifier))
    hover(point)
    QTest.qWait(420)
    view = popup.popup
    assert view and view.isVisible() and view.toPlainText() == text
    assert view.screen().availableGeometry().contains(view.geometry())
    assert view.verticalScrollBar().maximum() > 0 and view.horizontalScrollBar().maximum() == 0
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    assert view.cursorForPosition(view.viewport().rect().bottomRight()).blockNumber() >= 298
    hover(QPoint(1,1))
    QTest.qWait(300)
    assert not view.isVisible()
    popup.set_enabled(False)
    hover(point)
    QTest.qWait(420)
    assert not view.isVisible()


def test_long_single_paragraph_at_every_screen_corner(timeline):
    from marker_popup import MarkerPopup
    widget, doc = timeline
    view = MarkerPopup(widget)
    bounds = widget.screen().availableGeometry().adjusted(4,4,-4,-4)
    for pos in (bounds.topLeft(),bounds.bottomLeft(),bounds.topRight(),bounds.bottomRight()):
        for text in ('Long commentaire sur la pose. ' * 280,'x' * 5000):
            anchor = QRect(pos,pos)
            view.present(text, anchor)
            QTest.qWait(20)
            assert bounds.contains(view.geometry()) and not view.geometry().contains(pos)
            assert view.verticalScrollBar().maximum() > 0 and view.horizontalScrollBar().maximum() == 0
            view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
            assert view.cursorForPosition(view.viewport().rect().bottomRight()).position() == len(text)
    view.close()
