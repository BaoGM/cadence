# SPDX-License-Identifier: GPL-3.0-only
import json
import numpy as np
from PySide6.QtCore import Qt,QPointF,QEvent,QRectF,QTimer
from PySide6.QtGui import QMouseEvent,QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget
from test_drawing import application,window


def test_overlay_position_visibility_and_fullscreen(window,application):
    w=window; v=w.viewer; o=w.timecode_overlay
    v.set_frame(np.full((540,960,3),90,np.uint8)); w.refresh(); application.processEvents()
    assert not any(p.objectName()=='timecode_widget' for p in w.findChildren(QDockWidget))
    assert abs(o.rect().center().x()-o.bounds().center().x())<1
    assert abs(o.rect().bottom()-o.bounds().bottom())<1
    w.set_panel('timecode',False); assert o.rect().isEmpty() and not w.panel_actions['timecode'].isChecked()
    w.set_panel('timecode',True); w.toggle_fullscreen(); application.processEvents()
    assert not o.rect().isEmpty()
    w.panel_actions['timecode'].trigger(); assert o.isHidden()
    w.toggle_fullscreen(); assert o.isHidden()
    w.set_panel('timecode',True)
    o.set_position([.2,.4]); v.zoom=2; v.angle=37; v.pan=QPointF(80,-90)
    assert o.bounds().contains(o.rect())
    from playback_preferences import save,load,path
    save(w); assert json.loads(path().read_text())['timecode_position']==[.2,.4]
    o.set_position([.5,1]); load(w); assert o.position()==[.2,.4]
    o.set_position([float('nan'),0]); assert o.position()==[.2,.4]
    w.workspaces.reset(); assert o.position()==[.5,1]


def test_drag_overlay_does_not_scrub_or_draw(window,application):
    w=window; v=w.viewer; o=w.timecode_overlay
    v.set_frame(np.full((540,960,3),90,np.uint8)); w.drawing.choose_tool('brush'); application.processEvents()
    original=w.doc.state; start=o.rect().center(); end=start+QPointF(40,-50)
    QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=start.toPoint())
    event=QMouseEvent(QEvent.Type.MouseMove,end,v.mapToGlobal(end.toPoint()),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    application.sendEvent(v,event)
    QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=end.toPoint())
    assert w.doc.state==original and not w.drawing.stroke and v.origin is None
    assert o.anchor.y()<1 and o.anchor.x()>.5 and o.drag is None
    with_overlay=v.grab().toImage(); w.set_panel('timecode',False); without=v.grab().toImage()
    assert with_overlay!=without


def test_old_docked_timecode_layout_does_not_leave_an_empty_strip(window,application):
    from PySide6.QtWidgets import QLabel
    from workspace_modes import encoded
    w=window; w.workspaces.switch('read'); application.processEvents()
    dock=QDockWidget('Time code',w); dock.setObjectName('timecode_widget'); dock.setWidget(QLabel('00:00:00.000'))
    w.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,dock)
    w.splitDockWidget(dock,w.transport_widget,Qt.Orientation.Vertical); dock.show(); application.processEvents()
    state=encoded(w.saveState()); w.removeDockWidget(dock); dock.hide(); dock.setParent(None); dock.deleteLater()
    w.workspaces.layouts['read']=state; w.workspaces.apply('read'); application.processEvents()
    bottom=w.viewer.mapTo(w,w.viewer.rect().bottomLeft()).y()
    assert 0<=w.transport_widget.y()-bottom<=12


def test_overlay_stays_in_viewport_when_images_move_or_change_shape(window,application):
    w=window; v=w.viewer; o=w.timecode_overlay; w.request_frame=lambda:None
    v.set_frame(np.full((540,960,3),90,np.uint8)); application.processEvents()
    o.set_position([.5,1]); initial=o.rect()
    assert o.bounds()==QRectF(v.rect()).adjusted(8,8,-8,-8)
    for zoom,angle,pan in ((.05,0,QPointF()),(3,75,QPointF(300,-800)),(1,180,QPointF(10000,10000))):
        v.zoom=zoom; v.angle=angle; v.pan=pan
        assert o.rect()==initial
    v.zoom=1; v.angle=0; v.pan=QPointF(); v.comparing=True
    v.reference_rgb=np.full((540,960,3),140,np.uint8)
    for mode in ('horizontal','vertical','overlay','difference','wipe','front'):
        v.compare_mode=mode; v.apply_effect(); assert o.rect()==initial
    v.comparing=False; v.set_frame(np.full((80,1920,3),90,np.uint8))
    fitted=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio)
    assert o.rect().top()>v.height()/2+fitted.height()/2
    w.resize(1600,950); application.processEvents()
    assert o.bounds().contains(o.rect()) and abs(o.rect().center().x()-v.width()/2)<1


def test_timecode_context_lock_and_persistence(window,application):
    from playback_preferences import save,load,path
    from ui_text import tr
    w=window; v=w.viewer; o=w.timecode_overlay; w.request_frame=lambda:None
    v.set_frame(np.full((540,960,3),90,np.uint8)); w.drawing.choose_tool('cursor'); application.processEvents()
    seen=[]
    def toggle(expected):
        def choose():
            menu=application.activePopupWidget()
            try:
                action=next(a for a in menu.actions() if a.data()=='timecode_lock')
                seen.append((action.text(),action.isCheckable(),action.isChecked()))
                action.trigger()
            finally: menu.close()
        point=o.rect().center().toPoint(); QTimer.singleShot(20,choose)
        application.sendEvent(v,QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,v.mapToGlobal(point)))
        assert seen[-1]==(tr('Verrouiller la position du code temporel'),True,expected)
    toggle(False); assert o.locked
    position=o.position(); start=o.rect().center().toPoint(); end=start+QPointF(30,-40).toPoint()
    QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(v,end); QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=end)
    assert o.position()==position and o.drag is None
    save(w); assert json.loads(path().read_text())['timecode_locked'] is True
    o.set_locked(False); load(w); assert o.locked
    toggle(True); assert not o.locked
    o.set_locked(True); w.workspaces.reset(); assert not o.locked and o.position()==[.5,1]
