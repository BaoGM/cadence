# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent,QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from drawing import DrawingKey,Mark
from model import Document,State,Segment
from widgets import Timeline
from test_drawing import application


@pytest.fixture
def timeline(application):
    doc=Document(); doc.state=State((Segment(None,0,100),),drawings=(DrawingKey(40,41,(Mark(),)),))
    t=Timeline(); t.resize(1156,100); t.set_document(doc.state,{},24)
    def update(): t.set_document(doc.state,{},24)
    t.drawingResized.connect(lambda *args:(doc.resize_drawing(*args),update()))
    t.drawingMoved.connect(lambda *args:(doc.move_drawings(*args),update()))
    t.selected.connect(lambda a,b:(doc.select(a,b),update()))
    t.selectionDragged.connect(lambda a,b,f:(doc.select(a,b),update()))
    t.show(); application.processEvents()
    yield t,doc
    t.close(); t.deleteLater(); application.processEvents()


def move_mouse(t,x,y,modifiers=Qt.KeyboardModifier.NoModifier):
    local=QPointF(x,y); global_pos=QPointF(t.mapToGlobal(local.toPoint()))
    QApplication.sendEvent(t,QMouseEvent(QEvent.Type.MouseMove,local,global_pos,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,modifiers))


@pytest.mark.parametrize('delta',[-9,12])
def test_single_handle_extends_either_direction_and_undo(timeline,delta):
    t,d=timeline; original=d.state.drawings
    start=QPoint(round(t.x_for(40.5)),42)
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
    assert t.drawing_track.mode=='extend'
    end=start+QPoint(round(delta*t.track_width()/t.span()),0)
    move_mouse(t,end.x(),end.y())
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,end)
    key=d.state.drawings[0]
    assert (key.start,key.end)==(40+min(0,delta),41+max(0,delta))
    assert d.undo() and d.state.drawings==original
    assert d.redo() and d.state.drawings[0]==key


def test_single_handle_can_change_direction_before_release(timeline):
    t,d=timeline; start=QPoint(round(t.x_for(40.5)),42)
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
    move_mouse(t,start.x()-100,42); assert t.drawing_track.preview[0].start==30
    move_mouse(t,start.x()+70,42); assert t.drawing_track.preview[0].start==40
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(start.x()+70,42))
    assert (d.state.drawings[0].start,d.state.drawings[0].end)==(40,48)


def test_handles_stop_at_neighbor_and_escape_cancels(timeline):
    t,d=timeline
    d.state=replace(d.state,drawings=(DrawingKey(35,38,()),*d.state.drawings,DrawingKey(45,49,())))
    t.set_document(d.state,{},24); original=d.state.drawings
    start=QPoint(round(t.x_for(40.5)),42)
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
    move_mouse(t,start.x()+150,42); assert t.drawing_track.preview[1].end==45
    move_mouse(t,start.x()-150,42); assert t.drawing_track.preview[1].start==38
    QTest.keyClick(t,Qt.Key.Key_Escape)
    assert d.state.drawings==original and t.drawing_track.mode is None


def test_long_keys_keep_two_handles_and_alt_move(timeline):
    t,d=timeline; d.state=replace(d.state,drawings=(DrawingKey(40,50,(Mark(),)),)); t.set_document(d.state,{},24)
    assert t.drawing_track.resize_mode(d.state.drawings[0],t.x_for(40))=='left'
    assert t.drawing_track.resize_mode(d.state.drawings[0],t.x_for(50))=='right'
    assert t.drawing_track.resize_mode(d.state.drawings[0],t.x_for(45))=='click'
    start=QPoint(round(t.x_for(45)),42)
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,start)
    move_mouse(t,start.x()+100,42,Qt.KeyboardModifier.AltModifier)
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,QPoint(start.x()+100,42))
    assert (d.state.drawings[0].start,d.state.drawings[0].end)==(50,60)


def test_ruler_menu_merges_actions_without_duplicates(timeline):
    t,d=timeline
    menu=t.context_menu(QPoint(round(t.x_for(40.5)),20))
    actions=[a for a in menu.actions() if not a.isSeparator()]
    assert len({a.text() for a in actions})==len(actions)
    assert {'copy','cut','paste','units_time','units_frames','timeline_simple','add_marker','delete_markers'} <= {a.data() for a in actions}
    assert any(a.text()=='Supprimer les clés' and a.isEnabled() for a in actions)
    menu.deleteLater()


def test_shift_selection_on_key_strip_preserves_keys(timeline):
    t,d=timeline; original=d.state.drawings
    start=QPoint(round(t.x_for(30.5)),42); end=QPoint(round(t.x_for(50.5)),42)
    QTest.mousePress(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,start)
    move_mouse(t,end.x(),end.y(),Qt.KeyboardModifier.ShiftModifier)
    QTest.mouseRelease(t,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,end)
    assert d.state.selection==(30,51) and t.selection_track=='drawing'
    assert d.state.drawings==original


def test_dense_keys_keep_compact_height_and_render(application):
    t=Timeline(); t.resize(1200,100)
    keys=tuple(DrawingKey(f,f+1,(Mark(),)) for f in range(0,100000,5))
    state=State((Segment(None,0,100000),),drawings=keys,frame_markers=(10,50000,99999))
    t.set_document(state,{},24); assert t.height()==100
    image=QImage(t.size(),QImage.Format.Format_ARGB32_Premultiplied); t.render(image)
    for zoom in (1,10,100):
        t.zoom=zoom; t.view_start=40000 if zoom>1 else 0
        key=keys[8001]; assert t.drawing_track.hit(t.x_for(key.start+.5))==key
    t.close(); t.deleteLater()
