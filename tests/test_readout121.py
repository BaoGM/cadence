# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt,QEvent,QPointF,QRectF
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication
from drawing import DrawingKey,Mark
from test_drawing import application,window,pixels
from test_timeline102 import mouse,shift,SHIFT


@pytest.mark.parametrize('track,y',[('simple',35),('video',60),('audio',105),('drawing',158)])
def test_readout_during_drag_and_live_selection(window,application,track,y):
    w=window; w.request_frame=lambda:None; w.scrub_audio.set_enabled(False)
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(26,28,(Mark(),)),)); w.refresh()
    w.workspaces.set_timeline_simple(track=='simple'); t=w.timeline; application.processEvents()
    points={f:QPointF(t.x_for(f+.25),y) for f in (3,8,15,1)}
    mouse(t,QEvent.Type.MouseButtonPress,points[3])
    try:
        assert t.frame_indicator()[0]==3
        mouse(t,QEvent.Type.MouseMove,points[8]); assert t.frame_indicator()[0]==w.doc.state.position==8
        shift(t,True); mouse(t,QEvent.Type.MouseMove,points[15],SHIFT)
        assert w.doc.state.selection==(8,16) and t.frame_indicator()[0]==15
        mouse(t,QEvent.Type.MouseMove,points[1],SHIFT)
        assert w.doc.state.selection==(1,9) and t.frame_indicator()[0]==1
        application.sendEvent(t,QEvent(QEvent.Type.Leave)); assert t.frame_indicator()[0]==1
        shift(t,False); assert t.frame_indicator()[0]==1 and w.doc.state.selection is None
    finally: mouse(t,QEvent.Type.MouseButtonRelease,points[1]); shift(t,False)
    application.sendEvent(t,QEvent(QEvent.Type.Leave)); assert t.frame_indicator() is None


def test_zoomed_drag_uses_virtual_frame_not_warped_mouse_position(window,application):
    w=window; w.request_frame=lambda:None; w.scrub_audio.set_enabled(False); t=w.timeline
    t.zoom=5; t.view_start=10; t.clamp_view(); application.processEvents()
    start=QPointF(t.x_for(12.25),60); mouse(t,QEvent.Type.MouseButtonPress,start,SHIFT)
    try:
        # A relative drag may keep the physical pointer near its starting position after recentering.
        t._timeline_drag.move=lambda point:QPointF((25.25-t.drag_frame)/t.drag_scale,0)
        mouse(t,QEvent.Type.MouseMove,start,SHIFT)
        assert w.doc.state.position==25 and t.view_start>10
        assert t.frame_indicator()==(25,t.x_for(25))
        assert t.frame_for(start.x())!=25
    finally: mouse(t,QEvent.Type.MouseButtonRelease,start,SHIFT)


@pytest.mark.parametrize('transformed',[False,True])
def test_viewport_scrubbing_readout_stays_on_timeline(window,application,transformed):
    w=window; w.request_frame=lambda:None; w.scrub_audio.set_enabled(False)
    w.set_panel('timecode',False)
    w.drawing.choose_tool('cursor'); v=w.viewer; w.seek(4)
    if transformed: v.zoom=2; v.angle=37; v.pan=QPointF(40,-50)
    def render():
        image=QImage(v.size(),QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image)
        try: v.paint_scene(painter)
        finally: painter.end()
        return image
    before=render()
    start=QPointF(v.width()/2,v.height()/2)
    mouse(v,QEvent.Type.MouseButtonPress,start)
    try:
        assert w.timeline.frame_indicator()[0]==4
        assert render()==before
        mouse(v,QEvent.Type.MouseMove,start+QPointF(v.scrub_pixels*10,0))
        assert w.timeline.frame_indicator()[0]==14
        assert render()==before
        mouse(v,QEvent.Type.MouseMove,start+QPointF(v.scrub_pixels*3*6,0),SHIFT)
        assert w.timeline.frame_indicator()[0]==10
        mouse(v,QEvent.Type.MouseMove,start+QPointF(v.scrub_pixels*100,0))
        assert w.doc.state.position==30 and w.timeline.frame_indicator()[0]==29
        w.timeline_panel.hide(); assert render()==before
    finally: mouse(v,QEvent.Type.MouseButtonRelease,start)
    assert not w.timeline.external_scrubbing


def test_brush_and_canvas_navigation_do_not_show_scrub_readout(window,application):
    w=window; w.request_frame=lambda:None; v=w.viewer; w.drawing.choose_tool('brush')
    point=QPointF(v.width()/2,v.height()/2)
    mouse(v,QEvent.Type.MouseButtonPress,point)
    assert not w.timeline.external_scrubbing
    mouse(v,QEvent.Type.MouseButtonRelease,point)


def test_compact_badge_does_not_paint_over_tracks(window):
    t=window.timeline; t.hover_x=t.x_for(4.5)
    image=QImage(t.size(),QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    try: t.paint_frame_indicator(painter)
    finally: painter.end()
    rgba=pixels(image); ys,xs=np.nonzero(rgba[:,:,3])
    assert len(xs)>0 and ys.max()<30
    assert not np.any(rgba[30:,:,3])


@pytest.mark.parametrize('simple',[True,False])
def test_hover_highlight_is_one_frame_wide_and_translucent(window,application,simple):
    w=window; w.workspaces.set_timeline_simple(simple); t=w.timeline
    t.zoom=2; t.view_start=10; t.clamp_view(); application.processEvents()
    t.hover_x=t.x_for(12.5); position=w.doc.state.position
    def render():
        image=QImage(t.size(),QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image)
        try: t.paint_hover_highlight(painter)
        finally: painter.end()
        return pixels(image).copy()
    rgba=render(); ys,xs=np.nonzero(rgba[:,:,3])
    assert abs(xs.min()-t.x_for(12))<=1 and abs(xs.max()+1-t.x_for(13))<=1
    assert rgba[:,:,3].max()==(48 if simple else 16) and ys.min()>=24
    assert w.doc.state.position==position
    application.sendEvent(t,QEvent(QEvent.Type.Leave)); assert not np.any(render()[:,:,3])
