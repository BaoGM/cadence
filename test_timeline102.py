# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import json,time
import numpy as np
import pytest
from PySide6.QtCore import Qt,QEvent,QPointF
from PySide6.QtGui import QMouseEvent,QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from test_drawing import application,window
from test_cadence import prepared
from model import Document,State,Segment
from drawing import DrawingKey,Mark

SHIFT=Qt.KeyboardModifier.ShiftModifier
NONE=Qt.KeyboardModifier.NoModifier

def mouse(t,kind,point,mods=NONE):
    button=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    QApplication.sendEvent(t,QMouseEvent(kind,point,QPointF(t.mapToGlobal(point.toPoint())),button,buttons,mods))

def shift(t,pressed):
    QApplication.sendEvent(t,QKeyEvent(QEvent.Type.KeyPress if pressed else QEvent.Type.KeyRelease,Qt.Key.Key_Shift,SHIFT if pressed else NONE))

@pytest.mark.parametrize('track,y',[('simple',35),('video',60),('audio',105),('drawing',158),('drawing-key',158)])
def test_shift_can_change_mid_drag_without_jump(window,application,track,y):
    w=window; requested=[]; w.request_frame=lambda:requested.append(w.doc.state.position)
    keys=(DrawingKey(2,5,(Mark(),)),DrawingKey(25,27,(Mark(),))) if track=='drawing-key' else (DrawingKey(25,27,(Mark(),)),)
    w.doc.state=replace(w.doc.state,drawings=keys); w.refresh()
    w.workspaces.set_timeline_simple(track=='simple'); application.processEvents(); t=w.timeline
    points={f:QPointF(t.x_for(f+.25),y) for f in (3,7,12,2,16,21)}
    mouse(t,QEvent.Type.MouseButtonPress,points[3])
    mouse(t,QEvent.Type.MouseMove,points[7])
    shift(t,True)
    assert w.doc.state.selection==(7,8) and w.doc.state.position==7
    mouse(t,QEvent.Type.MouseMove,points[12],SHIFT)
    assert w.doc.state.selection==(7,13) and w.doc.state.position==12 and requested[-1]==12
    mouse(t,QEvent.Type.MouseMove,points[2],SHIFT)
    assert w.doc.state.selection==(2,8) and w.doc.state.position==2 and requested[-1]==2
    shift(t,False)
    assert w.doc.state.selection is None and w.doc.state.position==2
    mouse(t,QEvent.Type.MouseMove,points[16])
    assert w.doc.state.selection is None and w.doc.state.position==16
    shift(t,True); mouse(t,QEvent.Type.MouseMove,points[21],SHIFT)
    assert w.doc.state.selection==(16,22) and w.doc.state.position==21
    mouse(t,QEvent.Type.MouseButtonRelease,points[21],SHIFT); shift(t,False)
    assert w.doc.state.selection==(16,22) and w.doc.state.position==21
    assert not w.doc.undo_stack

@pytest.mark.parametrize('simple',[False,True])
def test_selected_cursor_decodes_live_video(window,application,prepared,simple):
    from media import PreviewReader
    w=window; media,_=prepared; d=Document(); d.media={media['id']:media}; d.state=State((Segment(media['id'],0,media['frames']),))
    d.saved_signature=d.signature(); w.install_doc(d); w.workspaces.set_timeline_simple(simple); application.processEvents()
    t=w.timeline; y=35 if simple else 60
    points={f:QPointF(t.x_for(f+.25),y) for f in (20,70,8)}
    mouse(t,QEvent.Type.MouseButtonPress,points[20],SHIFT)
    reader=PreviewReader()
    try:
        for frame in (70,8):
            mouse(t,QEvent.Type.MouseMove,points[frame],SHIFT)
            deadline=time.monotonic()+5
            while getattr(w,'rendered_token',None)!=w.token and time.monotonic()<deadline: QTest.qWait(10)
            assert w.rendered_token==w.token and d.state.position==frame
            assert np.array_equal(w.viewer.rgb,reader.read(media,frame))
            assert d.state.selection==(min(frame,20),max(frame,20)+1)
        mouse(t,QEvent.Type.MouseButtonRelease,points[8],SHIFT)
    finally: reader.close()

def test_simplified_context_toggle_preserves_workspace_and_saved_mode(window,application):
    w=window; w.request_frame=lambda:None; t=w.timeline
    before={k:p.isHidden() for k,p in w.workspaces.panels.items()}; w.select(2,8)
    def toggle(y):
        menu=t.context_menu(QPointF(t.x_for(4),y))
        action=next(a for a in menu.actions() if a.data()=='timeline_simple')
        assert action.isChecked()==bool(t.simple)
        action.trigger(); menu.deleteLater(); application.processEvents()
    toggle(60)
    assert t.simple and t.height()==44 and w.workspaces.mode=='edit'
    assert before=={k:p.isHidden() for k,p in w.workspaces.panels.items()} and w.doc.state.selection==(2,8)
    assert json.loads(w.workspaces.path.read_text(encoding='utf-8'))['simple']['edit']
    w.workspaces.switch('read'); w.workspaces.switch('edit'); assert t.simple
    toggle(35); assert not t.simple and t.height()==100 and w.doc.state.selection==(2,8)
    assert not json.loads(w.workspaces.path.read_text(encoding='utf-8'))['simple']['edit']
