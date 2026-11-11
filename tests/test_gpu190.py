# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent
from PySide6.QtGui import QImage,QPainter,QColor,QMouseEvent
from test_d3d160 import application,surface,image_pixels
from drawing import Mark,DrawingKey,render_layer
from drawing_cache import DrawingRasterCache
from drawing_gpu import paint_layers,collect_layer
import native_d3d


def keys():
    line=Mark(points=((.1,.2,1),(.9,.8,1)),size=.08,color='#ff6433',opacity=.7,pressure=False)
    erase=Mark(tool='eraser',points=((.5,.5,1),),size=.2,pressure=False)
    return tuple(DrawingKey(i,i+1,(replace(line,color=color),erase)) for i,color in enumerate(('#00ffff','#ffffff','#ff0000','#00ff00','#3333ff')))


@pytest.mark.parametrize('flip',[False,True])
@pytest.mark.parametrize('clip',[False,True])
def test_gpu_drawing_opacity_eraser_clip_and_reuse(surface,flip,clip):
    renderer,_,_=surface; width,height=160,100
    source=np.full((height,width,3),[40,50,60],np.uint8); packet=native_d3d.prepare(source)
    cache=DrawingRasterCache(); drawings=keys()
    revisions=[]
    for frame in (2,3,2):
        overlay=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); overlay.fill(Qt.GlobalColor.transparent)
        painter=QPainter(overlay); layers=[]
        if clip: painter.setClipRect(QRectF(0,0,80,100))
        def submit(p,r,image,alpha):
            layer=collect_layer(p,r,image,alpha)
            if layer: layers.append(layer)
        paint_layers(painter,QRectF(0,0,width,height),drawings,frame,width,height,3,3,1,cache,flip,flip,submit)
        painter.end(); revisions.append([x[0].cacheKey() for x in layers])
        assert renderer.paint(packet,[0,0,width,0,0,height,width,height],None,width,height,layers=layers),renderer.error()
        expected=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); expected.fill(QColor(40,50,60))
        ink=render_layer(drawings,frame,width,height,3,3,1,cache=cache)
        if flip: ink=ink.mirrored(True,True)
        painter=QPainter(expected)
        if clip: painter.setClipRect(QRectF(0,0,80,100))
        painter.drawImage(0,0,ink); painter.end()
        delta=np.abs(renderer.readback().astype(int)-image_pixels(expected).astype(int))
        assert delta.max()<=4,delta.max()
    assert revisions[0]==revisions[2]


@pytest.mark.parametrize('mode',['overlay','difference'])
def test_gpu_fitted_pair(surface,mode):
    renderer,_,_=surface
    a=np.full((60,100,3),[20,100,200],np.uint8); b=np.full((80,40,3),[200,100,20],np.uint8)
    from comparison import compose
    from media import exposure_lut
    for swapped in (False,True):
        packet=native_d3d.prepare(a,b,mode=mode,ev=.5,opacity=.3,gain=1.4,swapped=swapped)
        assert packet is not None
        assert renderer.paint(packet,[0,0,100,0,0,60,100,60],None,100,60),renderer.error()
        expected=compose(exposure_lut(.5)[a],exposure_lut(.5)[b],mode,.3,1.4,swapped)
        assert np.abs(renderer.readback()[:,:,:3].astype(int)-expected).max()<=2


def test_cursor_leave_release_and_reenter(application,monkeypatch):
    monkeypatch.setenv('CADENCE_RENDERER','software')
    from widgets import Viewer
    from drag import ContinuousDrag
    v=Viewer(); v.show(); application.processEvents(); guard=v.cursor_guard
    try:
        guard.boundary(False); v.setCursor(Qt.CursorShape.ClosedHandCursor)
        v.origin=QPointF(10,10); v._video_drag=ContinuousDrag(QPointF(10,10)); releases=[]; v.scrubActiveChanged.connect(releases.append)
        guard.eventFilter(v,QEvent(QEvent.Type.Leave))
        assert v.cursor().shape()==Qt.CursorShape.ArrowCursor
        guard.release(); assert v.origin is None and releases==[False]
        guard.boundary(False); assert v.cursor().shape()==Qt.CursorShape.OpenHandCursor
        guard.eventFilter(v.window(),QEvent(QEvent.Type.WindowDeactivate))
        assert v.cursor().shape()==Qt.CursorShape.ArrowCursor
        guard.boundary(False); v.setCursor(Qt.CursorShape.CrossCursor); guard.boundary(True)
        assert v.cursor().shape()==Qt.CursorShape.ArrowCursor
        guard.boundary(False); assert v.cursor().shape()==Qt.CursorShape.CrossCursor
        v.hide(); application.processEvents(); assert not guard.active
        v.show(); application.processEvents(); assert guard.active
    finally: v.close(); v.deleteLater(); application.processEvents()


def test_gpu_drawing_cache_bounded(surface):
    renderer,_,_=surface
    for i in range(270):
        image=QImage(24,24,QImage.Format.Format_ARGB32_Premultiplied);image.fill(QColor(i%255,128,64,150))
        layer=(image,(0,0,24,0,0,24,24,24),.5,(0,0,1,1))
        assert renderer.paint(None,None,None,24,24,layers=[layer])
    stats=renderer.drawing_stats()
    assert stats['textures']==256 and stats['bytes']==256*24*24*4 and stats['uploads']==270
    assert renderer.paint(None,None,None,24,24,layers=[layer])
    assert renderer.drawing_stats()==stats


def test_opengl_layers_and_fitted_comparison(application):
    from test_gpu160 import Surface,rendered_pixels
    import native_gpu
    class Probe(Surface):
        def paintGL(self):
            p=QPainter(self)
            try:
                p.fillRect(0,0,self.width(),self.height(),QColor(40,50,60))
                if self.packet is not None:
                    self.used=self.compositor.paint(p,self.packet,QRectF(0,0,160,100))
                else:
                    p.setClipRect(QRectF(0,0,80,100))
                    paint_layers(p,QRectF(0,0,160,100),keys(),2,160,100,3,3,1,self.cache,True,True)
            finally:p.end()
    v=Probe();v.cache=DrawingRasterCache();v.resize(160,100);v.show()
    try:
        actual=rendered_pixels(v);expected=QImage(160,100,QImage.Format.Format_ARGB32_Premultiplied);expected.fill(QColor(40,50,60))
        ink=render_layer(keys(),2,160,100,3,3,1).mirrored(True,True)
        p=QPainter(expected);p.setClipRect(QRectF(0,0,80,100));p.drawImage(0,0,ink);p.end()
        assert np.abs(actual.astype(int)-image_pixels(expected).astype(int)).max()<=4
        from comparison import compose
        a=np.full((100,160,3),[20,80,160],np.uint8);b=np.full((200,80,3),[100,50,30],np.uint8)
        for mode in ('overlay','difference'):
            v.packet=native_gpu.prepare(a,b,mode=mode,opacity=.3,gain=1.4)
            actual=rendered_pixels(v);expected=compose(a,b,mode,.3,1.4)
            assert v.used and np.abs(actual[:,:,:3].astype(int)-expected).max()<=2
    finally:
        v.compositor.close();v.close();v.host.deleteLater()
        application.sendPostedEvents(None,QEvent.Type.DeferredDelete);application.processEvents()


def test_gpu_drawing_cache_byte_budget(surface):
    renderer,_,_=surface
    for i in range(10):
        image=QImage(3840,2160,QImage.Format.Format_ARGB32_Premultiplied);image.fill(QColor(i*20,80,120))
        layer=(image,(0,0,32,0,0,18,32,18),1.,(0,0,1,1))
        assert renderer.paint(None,None,None,32,18,layers=[layer])
        assert renderer.drawing_stats()['bytes']<=256*1024**2
    assert renderer.drawing_stats()['textures']==8
    assert np.abs(renderer.readback()[9,16,:3].astype(int)-[180,80,120]).max()<=1
