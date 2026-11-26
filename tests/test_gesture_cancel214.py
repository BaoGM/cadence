# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from drawing import DrawingKey, Mark
from model import Segment
from test_drawing import application, window
from test_timeline200 import move_pointer, point, timeline
from timeline_skin import marker_areas


def right_cancel(app, widget, pos, mods=Qt.NoModifier):
    QTest.mousePress(widget, Qt.RightButton, mods, pos)
    QTest.mouseRelease(widget, Qt.RightButton, mods, pos)
    context = QContextMenuEvent(QContextMenuEvent.Mouse, pos, widget.mapToGlobal(pos))
    app.sendEvent(widget, context)
    assert context.isAccepted()
    QTest.mouseRelease(widget, Qt.LeftButton, mods, pos)


def test_frame_number_without_mouse(timeline, monkeypatch):
    import widgets
    t, doc = timeline
    recorded = []
    original = widgets.paint_frame_number

    def observe(painter, label, *args, **kwargs):
        if kwargs.get('active'):
            recorded.append(label)
        return original(painter, label, *args, **kwargs)

    monkeypatch.setattr(widgets, 'paint_frame_number', observe)
    t.hover_x = None
    t.grab()
    assert recorded == [t.tick_label(doc.state.position)]


def test_transport_hover_on_button_tracks_frame(window, application):
    w = window
    w.workspaces.switch('read')
    w.set_panel('transport', True)
    application.processEvents()
    button = w.play_btn
    pos = button.rect().center()
    QTest.mouseMove(button, pos - QPoint(3, 0))
    QTest.mouseMove(button, pos)
    t = w.timeline
    x = t.mapFromGlobal(button.mapToGlobal(pos)).x()
    assert t.transport_hover_x == x and t.hover_frame() == t.frame_for(x)
    assert w.doc.state.position == 0 and not w.transport.running
    QTest.mouseMove(w.viewer, w.viewer.rect().center())
    assert t.transport_hover_x is None


@pytest.mark.parametrize('gesture', ['move', 'copy', 'marker', 'key', 'range', 'brush', 'shape', 'size', 'crop'])
def test_right_cancel_before_release_without_menu_or_undo(window, application, monkeypatch, gesture):
    w=window
    monkeypatch.setattr(w, 'request_frame', lambda: None)
    w.scrub_audio.set_enabled(False)
    t, v, d = w.timeline, w.viewer, w.drawing
    w.doc.state=replace(w.doc.state, segments=(Segment('a',0,10),Segment('a',10,20)),
                        drawings=(DrawingKey(12,17,(Mark(),)),), frame_markers=(8,), position=5, selection=(3,7))
    w.refresh()
    menus=[]
    def close_menu():
        menu=application.activePopupWidget()
        if isinstance(menu,QMenu):
            menus.append(True)
            menu.close()
    monitor=QTimer(w)
    monitor.timeout.connect(close_menu)
    monitor.start(10)
    mods = Qt.NoModifier
    if gesture in ('brush','shape','size','crop'):
        widget=v
        start=v.rect().center()
        end=start+QPoint(34,14)
        if gesture=='crop':
            w.clip_tools.activate('crop')
            mods=Qt.AltModifier
        else:
            d.choose_tool('rectangle' if gesture=='shape' else 'brush')
        if gesture=='size': mods=Qt.ShiftModifier
    else:
        widget=t
        if gesture=='marker':
            start=next(marker_areas(t))[2].center().toPoint()
        elif gesture=='key':
            start=QPoint(round(t.x_for(17)),t.track_y('drawing'))
        else:
            start=point(t,4)
        end=QPoint(round(t.x_for(24)),start.y())
        if gesture in ('move','copy'): mods=Qt.AltModifier
        if gesture in ('copy','range'): mods|=Qt.ShiftModifier
    before=w.doc.state
    history=len(w.doc.undo_stack)
    size=d.size.value()
    QTest.mousePress(widget,Qt.LeftButton,mods,start)
    move_pointer(widget,end,mods)
    if gesture=='key': assert t.drawing_track.change
    if gesture=='marker': assert t.marker_drag.destination is not None
    if gesture=='range': assert w.doc.state.selection!=before.selection
    if gesture in ('move','copy'): assert t.clip_preview.phase=='lift'
    if gesture in ('brush','shape'): assert d.stroke is not None
    if gesture=='size': assert d.size.value()!=size
    if gesture=='crop': assert w.clip_tools.drag
    right_cancel(application,widget,end,mods)
    assert w.doc.state==before and len(w.doc.undo_stack)==history
    assert not menus and d.stroke is None and d.size.value()==size
    assert t.marker_drag.source is None and t.drawing_track.mode is None and not t.gesture
    assert w.clip_tools.mode is None
    QTest.mousePress(widget,Qt.RightButton,Qt.NoModifier,start)
    QTest.mouseRelease(widget,Qt.RightButton,Qt.NoModifier,start)
    application.sendEvent(widget,QContextMenuEvent(QContextMenuEvent.Mouse,start,widget.mapToGlobal(start)))
    assert menus
    monitor.stop()
