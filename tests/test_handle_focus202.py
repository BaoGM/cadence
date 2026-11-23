# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest

from drawing import DrawingKey, Mark
from test_drawing import application, window
from test_wipe1217 import display_point


def tab_to(target, app):
    previous = target.previousInFocusChain()
    while previous is not target and not (previous.isVisible() and previous.isEnabled() and previous.focusPolicy() & Qt.TabFocus):
        previous = previous.previousInFocusChain()
    previous.setFocus()
    for _ in range(20):
        QTest.keyClick(app.focusWidget(), Qt.Key_Tab)
        if target.hasFocus():
            return
    pytest.fail(f'Tab failed to reach {target}')


@pytest.mark.parametrize('simple', [False, True])
def test_key_handles_real_focus_navigation_and_undo(window, application, simple):
    w=window
    w.request_frame=lambda:None
    w.workspaces.set_timeline_simple(simple)
    w.doc.state=replace(w.doc.state,position=7,drawings=(DrawingKey(9,12,(Mark(),)),DrawingKey(14,16,(Mark(),))))
    w.refresh()
    w.activateWindow(); application.processEvents()
    t=w.timeline
    before=w.doc.state
    tab_to(t, application)
    QTest.keyClick(t,Qt.Key_Right)
    assert w.doc.state.position==8 and w.doc.state.drawings==before.drawings
    QTest.keyClick(t,Qt.Key_Return)
    handle=t.drawing_track.focus_handle
    assert handle.hasFocus() and '9' in handle.accessibleName()
    QTest.keyClick(handle,Qt.Key_Right)
    assert w.doc.state.drawings[0].start==10 and w.doc.state.position==10
    QTest.keyClick(handle,Qt.Key_Tab)
    QTest.keyClick(handle,Qt.Key_Right)
    assert w.doc.state.drawings[0].end==14
    assert w.doc.state.position==10
    count=len(w.doc.undo_stack)
    QTest.keyClick(handle,Qt.Key_Right)
    assert w.doc.state.drawings[0].end==14 and len(w.doc.undo_stack)==count
    QTest.keyClick(handle,Qt.Key_Z,Qt.ControlModifier)
    assert w.doc.state.drawings[0].end==13
    # The edit changed the underlying exposure. The stale handle yields to playback.
    QTest.keyClick(application.focusWidget(),Qt.Key_Right)
    assert w.doc.state.position==11 and w.doc.state.drawings[0].end==13
    key=w.doc.state.drawings[0]
    y=t.track_y('drawing')+2
    QTest.mouseClick(t,Qt.LeftButton,pos=QPoint(round(t.x_for(key.start)),y))
    assert handle.hasFocus() and t.drawing_track.focus_part_name=='left'
    QTest.keyClick(handle,Qt.Key_Left)
    assert w.doc.state.drawings[0].start==9 and w.doc.state.drawings[0].end==13
    QTest.keyClick(handle,Qt.Key_Escape)
    assert t.hasFocus()
    pos=w.doc.state.position
    QTest.keyClick(t,Qt.Key_Left)
    assert w.doc.state.position==pos-1 and w.doc.state.drawings[0].start==9


@pytest.mark.parametrize('workspace',['read','edit'])
def test_wipe_handle_requires_focus_and_restores_playback(window,application,workspace):
    w=window
    w.request_frame=lambda:None
    w.workspaces.switch(workspace)
    v=w.viewer
    v.comparing=True; v.compare_mode='wipe'
    v.reference_rgb=np.zeros((100,200,3),dtype=np.uint8)
    v.set_frame(v.reference_rgb.copy())
    w.activateWindow(); application.processEvents()
    tab_to(v, application)
    next_action=w.action_registry['Lecture/Image suivante'][0]
    spy=QSignalSpy(next_action.triggered)
    QTest.keyClick(v,Qt.Key_Right)
    assert spy.count()==1 and v.wipe_position==.5
    QTest.keyClick(v,Qt.Key_Enter)
    handle=w.wipe_interaction.focus_handle
    assert handle.hasFocus()
    QTest.keyClick(handle,Qt.Key_Right)
    assert spy.count()==1 and v.wipe_position==.52
    QTest.keyClick(handle,Qt.Key_Escape)
    assert v.hasFocus() and v.wipe_position==.5
    point=display_point(v,.5,.5).toPoint()
    QTest.mouseClick(v,Qt.LeftButton,pos=point)
    assert handle.hasFocus()
    QTest.keyClick(handle,Qt.Key_Right)
    QTest.keyClick(handle,Qt.Key_Tab)
    assert not handle.hasFocus() and v.wipe_position==.52
    v.setFocus()
    QTest.keyClick(v,Qt.Key_Right)
    assert spy.count()==2 and v.wipe_position==.52
