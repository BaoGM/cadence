# SPDX-License-Identifier: GPL-3.0-only
import time
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import QPointF,Qt
from PySide6.QtGui import QImage,QPainter,QTransform
from PySide6.QtTest import QTest
from test_drawing import application,window
from drawing import Mark,DrawingKey
from model import State,Segment,RATE
from engine import Transport,PCMDevice


def test_loop_change_keeps_clock_and_device(window):
    w=window; t=w.transport
    class PCM:
        def read(self,at,n): return b'\1\0\1\0'*n
        def close(self): pass
    t.running=True; t.a=10; t.b=34; t.fps=Fraction(24); t.start_frame=10
    t.started=time.perf_counter()-2.25; t.passes=0; t.pcm=PCM()
    t.device=PCMDevice(t.pcm,0,0,RATE,0); old_device=t.device; old_clock=t.started
    w.timer.start(); w.play_btn.setSymbol('pause')
    w.set_loop(False)
    assert t.running and t.device is old_device and t.started==old_clock and t.passes==3
    assert not t.clock()[2] and w.timer.isActive() and w.play_btn.symbol=='pause'
    w.set_loop(True)
    assert t.passes==0 and t.device.passes==0 and t.started==old_clock
    t.started=time.perf_counter()-.25; t.passes=1
    t.device.position=t.device.b; t.device.finished=True
    w.set_loop(True)
    assert not t.device.finished and t.device.readData(40)==b'\1\0\1\0'*10
    t.hold(); before=t.started; t.set_loop(False)
    assert t.suspended and not t.running and t.started==before and t.passes==1
    w.pause()


def test_selection_measurement_both_modes(window):
    t=window.timeline
    t.set_document(State((Segment('a',0,200),),selection=(10,58)),{},Fraction(24))
    for simple in (False,True):
        t.simple=simple; t.resize(900,100)
        for units,text in [('frames','48 img'),('time','00:02.000')]:
            t.units=units; assert t.selection_label()==text
            image=QImage(t.size(),QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image); t.paint_selection_label(painter); painter.end()
            from test_drawing import pixels
            ys,xs=np.nonzero(pixels(image)[:,:,3])
            center=(t.x_for(10)+t.x_for(58))/2
            assert len(xs)>0 and abs((xs.min()+xs.max()+1)/2-center)<2
    t.state=replace(t.state,selection=(10,11)); t.units='frames'
    assert t.selection_label()=='1 img'


def test_picker_visible_pixels_transformed_and_no_key(window):
    w=window; v=w.viewer; d=w.drawing
    v.resize(640,360); v.set_frame(np.full((360,640,3),[25,75,130],np.uint8))
    w.doc.state=replace(w.doc.state,position=5,selection=(10,15),drawings=(DrawingKey(5,6,(Mark(points=((.5,.5,1.),),size=.2,color='#ff0000',pressure=False),)),))
    d.invalidate(); d.panel.hide(); d.choose_tool('picker')
    assert w.doc.state.position==5 and not d.panel.isVisible()
    before=w.doc.state
    d.sample(QPointF(320,180)); assert d.wheel.color()=='#ff0000'
    d.sample(QPointF(130,100)); assert d.wheel.color()=='#194b82'
    v.zoom=1.7; v.angle=27; v.pan=QPointF(20,15)
    d.sample(QPointF(340,195)); assert d.wheel.color()=='#ff0000'
    assert w.doc.state is before
    d.choose_tool('brush'); w.doc.state=replace(before,selection=None); d.invalidate()
    QTest.mouseClick(v,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,QPointF(340,195).toPoint())
    assert d.tool.currentData()=='brush' and d.wheel.color()=='#ff0000' and w.doc.state.drawings==before.drawings
    assert not d.stroke and not getattr(d,'sampling',False)


def test_spatial_gpu_metadata_cpu_fallback_and_picker(application):
    from widgets import Viewer
    from native_d3d import prepare
    v=Viewer(); v.resize(640,360); v.renderer='direct3d'; v.surface=SimpleNamespace(compositor=SimpleNamespace(failed=False),update=lambda:None)
    a=np.full((60,100,3),[20,40,80],np.uint8); b=np.full_like(a,[180,100,60])
    v.reference_rgb=b; v.comparing=True
    try:
        for mode in ('horizontal','vertical','wipe','front'):
            for swapped in (False,True):
                v.compare_mode=mode; v.compare_swapped=swapped; v.set_frame(a)
                assert v.gpu_packet is not None
                image=v.cpu_preview(); size=v.image_size()
                assert image.size()==size
                expect=(20,40,80) if not swapped else (180,100,60)
                assert image.pixelColor(1,1).getRgb()[:3]==expect
        v.compare_mode='wipe'; v.compare_swapped=False; v.apply_effect(); v.wipe_position=.25; v.gpu_packet.wipe=.25
        assert v.cpu_preview().pixelColor(30,30).getRgb()[:3]==(180,100,60)
        assert v.sample_color(QPointF(480,180))=='#b4643c'
    finally: v.surface=None; v.close()
