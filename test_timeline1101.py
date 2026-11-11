# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from test_drawing import application,window
from model import Document,State,Segment


@pytest.mark.parametrize('simple,track',[(True,'video'),(False,'video'),(False,'audio')])
def test_shift_double_click_selects_whole_segment(window,application,simple,track):
    w=window; t=w.timeline; w.request_frame=lambda:None
    w.doc.state=State((Segment('a',0,10),Segment('a',10,25),Segment(None,0,5)),
                      audio_segments=(Segment('a',0,15),Segment('a',15,25),Segment(None,0,5)))
    t.simple=simple; w.refresh(); application.processEvents()
    point=QPoint(round(t.x_for(18)),35 if simple else t.track_y(track)+9)
    QTest.mouseClick(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,point)
    QTest.mouseDClick(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,point)
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,point)
    assert w.doc.state.selection==((15,25) if track=='audio' else (10,25))
    assert t.selection_track==track and t.gesture is None
    assert abs(w.doc.state.position-18)<=1


@pytest.mark.parametrize('simple',[False,True])
def test_alt_drag_does_not_select_moved_media(window,application,simple):
    w=window; t=w.timeline; w.request_frame=lambda:None
    w.doc.state=State((Segment('a',0,10),Segment('a',10,20),Segment('a',20,30)),selection=(0,10))
    initial=w.doc.state; t.simple=simple; w.refresh(); application.processEvents()
    y=35 if simple else t.track_y('video')+9
    start=QPoint(round(t.x_for(4)),y); end=QPoint(round(t.x_for(29)),y)
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,start)
    QTest.mouseMove(t,end,20)
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,end)
    assert w.doc.state.segments[-1]==initial.segments[0]
    assert w.doc.state.selection is None and w.doc.state.loop_range is None
    assert w.doc.undo(); assert w.doc.state==initial
    assert w.doc.redo(); assert w.doc.state.selection is None


@pytest.mark.parametrize('track',['linked','audio','video'])
def test_move_clears_selection_but_duplicate_still_selects(track):
    d=Document(); d.state=State((Segment('a',0,10),Segment('b',0,10)),selection=(0,10))
    assert d.move_range(0,10,20,track); assert d.state.selection is None
    assert d.duplicate_range(0,10); assert d.state.selection==(10,20)


def test_compact_layout_preserves_custom_arrangement(window,application):
    w=window; modes=w.workspaces
    w.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,w.comparison_panel)
    application.processEvents(); original=w.library.geometry()
    modes.fit_comparison_stack(); application.processEvents()
    assert w.library.geometry()==original
    modes.reset(); application.processEvents()
    panel=w.comparison_panel; scroll=panel.widget(); body=scroll.widget()
    assert scroll.verticalScrollBar().maximum()==0
    assert abs(panel.height()-(body.minimumSizeHint().height()+2*scroll.frameWidth()))<=3
    modes.capture(); original=w.library.height()
    modes.switch('read'); modes.switch('edit'); application.processEvents()
    assert abs(w.library.height()-original)<=2


def test_compact_layout_uses_styled_control_heights(window,application):
    from app import STYLE
    w=window; previous=application.styleSheet()
    try:
        application.setStyleSheet(STYLE); w.hide(); w.resize(1600,900)
        w.workspaces.reset(); w.show(); QTest.qWait(50)
        scroll=w.comparison_panel.widget()
        assert scroll.verticalScrollBar().maximum()==0
        assert w.comparison_panel.height()>=scroll.widget().minimumSizeHint().height()
        assert w.library.height()>250
    finally:
        application.setStyleSheet(previous)
