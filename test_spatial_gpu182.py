# SPDX-License-Identifier: GPL-3.0-only
import numpy as np
import pytest
from PySide6.QtCore import Qt,QRectF,QEvent
from PySide6.QtGui import QPainter,QColor,QImage
from PySide6.QtTest import QTest
from test_d3d160 import application,surface
from test_gpu160 import Surface,rendered_pixels
import native_gpu,native_d3d


def reference(a,b,mode,ev,swapped,flip,wipe=.375):
    from comparison import compose
    from media import exposure_lut
    aa=exposure_lut(ev)[a] if ev else a
    bb=exposure_lut(ev)[b] if ev else b
    if flip: aa=aa[::-1,::-1]; bb=bb[::-1,::-1]
    return compose(aa,bb,mode,swapped=swapped,wipe=wipe)


@pytest.mark.parametrize('mode',['horizontal','vertical','wipe','front'])
def test_d3d_spatial_pixels(surface,mode):
    renderer,host,child=surface; rng=np.random.default_rng(182)
    a=rng.integers(0,256,(32,48,3),np.uint8); b=rng.integers(0,256,a.shape,np.uint8)
    for ev in (0,.7):
        for swapped in (False,True):
            for flip in (False,True):
                expected=reference(a,b,mode,ev,swapped,flip); h,w=expected.shape[:2]
                packet=native_d3d.prepare(a,b,mode=mode,ev=ev,swapped=swapped,flip_h=flip,flip_v=flip,wipe=.375)
                assert renderer.paint(packet,[0,0,w,0,0,h,w,h],None,w,h),renderer.error()
                actual=renderer.readback()[:,:,:3]
                assert np.max(np.abs(actual.astype(int)-expected))<=1,(mode,ev,swapped,flip)


@pytest.mark.parametrize('mode',['horizontal','vertical','wipe'])
def test_d3d_spatial_different_aspects(surface,mode):
    renderer,_,_=surface
    a=np.full((60,100,3),[30,60,90],np.uint8); b=np.full((80,40,3),[200,150,100],np.uint8)
    expected=reference(a,b,mode,0,False,False); h,w=expected.shape[:2]
    packet=native_d3d.prepare(a,b,mode=mode,wipe=.375)
    assert renderer.paint(packet,[0,0,w,0,0,h,w,h],None,w,h)
    assert np.max(np.abs(renderer.readback()[:,:,:3].astype(int)-expected))<=1


class SpatialProbe(Surface):
    def paintGL(self):
        p=QPainter(self)
        try:
            p.fillRect(self.host.rect(),QColor('black'))
            self.used=self.compositor.paint(p,self.packet,QRectF(0,0,self.width(),self.height()))
        finally: p.end()


def test_opengl_spatial_pixels(application):
    rng=np.random.default_rng(183); a=rng.integers(0,256,(32,48,3),np.uint8); b=rng.integers(0,256,a.shape,np.uint8)
    window=SpatialProbe()
    try:
        for mode in ('horizontal','vertical','wipe','front'):
            for ev in (0,.7):
                expected=reference(a,b,mode,ev,True,True); h,w=expected.shape[:2]
                window.packet=native_gpu.prepare(a,b,mode=mode,ev=ev,swapped=True,flip_h=True,flip_v=True,wipe=.375)
                window.resize(w,h); window.show()
                actual=rendered_pixels(window)
                assert window.used and np.max(np.abs(actual[:,:,:3].astype(int)-expected))<=1,(mode,ev)
    finally:
        window.compositor.close(); window.close(); window.host.deleteLater()
        application.sendPostedEvents(None,QEvent.Type.DeferredDelete); application.processEvents()
