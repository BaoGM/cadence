# SPDX-License-Identifier: GPL-3.0-only
import gc
from dataclasses import replace,asdict
import numpy as np
import pytest
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication
import native_render
from drawing import Mark,DrawingKey,render_marks,render_layer
from drawing_cache import DrawingRasterCache
from model import State,Segment


@pytest.fixture(scope='module')
def application():
    app=QApplication.instance() or QApplication([])
    return app


@pytest.fixture(autouse=True)
def native(monkeypatch):
    monkeypatch.setenv('CADENCE_NATIVE_RENDER','1')
    assert native_render.available()


def rgb_pixels(image):
    return np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()


@pytest.mark.parametrize('ev',[-10,-1.3,0,1.7,10])
@pytest.mark.parametrize('mode',['overlay','difference'])
def test_exhaustive_channel_pairs(ev,mode):
    from comparison import compose
    from media import exposure_lut
    a=np.repeat(np.broadcast_to(np.arange(256,dtype=np.uint8)[:,None,None],(256,256,3)),1,axis=0).copy()
    b=a.transpose(1,0,2).copy()
    for opacity,gain in ((0,1),(.01,1.3),(.41,2.2),(.5,4.5),(.99,20),(1,1)):
        for swapped in (False,True):
            aa=exposure_lut(ev)[a] if ev else a
            bb=exposure_lut(ev)[b] if ev else b
            expected=compose(aa,bb,mode,opacity,gain,swapped)
            actual=native_render.rgb_image(a,b,ev=ev,mode=mode,opacity=opacity,gain=gain,swapped=swapped)
            np.testing.assert_array_equal(rgb_pixels(actual),expected)


@pytest.mark.parametrize('flip_h,flip_v',[(False,False),(True,False),(False,True),(True,True)])
def test_strides_padding_and_owned_output(flip_h,flip_v):
    from comparison import compose
    from media import exposure_lut
    rng=np.random.default_rng(8)
    a=rng.integers(0,256,(27,39,3),dtype=np.uint8)[::-2,1::2,::-1]
    b=rng.integers(0,256,(27,39,3),dtype=np.uint8)[::-2,1::2,:]
    for mode in ('single','overlay','difference'):
        def effect(arr):
            arr=exposure_lut(.7)[arr]
            if flip_h: arr=arr[:,::-1]
            if flip_v: arr=arr[::-1]
            return arr
        expected=effect(a) if mode=='single' else compose(effect(a),effect(b),mode,.37,1.7,True)
        image=native_render.rgb_image(a,b,mode=mode,ev=.7,opacity=.37,gain=1.7,swapped=True,flip_h=flip_h,flip_v=flip_v)
        np.testing.assert_array_equal(rgb_pixels(image),expected)
        a_copy=a.copy(); a[:]=0; gc.collect()
        np.testing.assert_array_equal(rgb_pixels(image),expected)
        a[:]=a_copy


def test_fallbacks_and_validation(monkeypatch):
    a=np.zeros((4,5,3),np.uint8)
    assert native_render.rgb_image(a,None,mode='overlay') is None
    assert native_render.rgb_image(a,a,mode='wipe') is None
    assert native_render.rgb_image(a.astype(np.float32),ev=1) is None
    assert native_render.rgb_image(a,ev=float('nan')) is None
    monkeypatch.setenv('CADENCE_NATIVE_RENDER','0')
    assert native_render.rgb_image(a,ev=1) is None
    monkeypatch.setenv('CADENCE_NATIVE_RENDER','1')
    import native_graphics
    def missing(): raise OSError('missing rendering module')
    native_render._library.cache_clear()
    monkeypatch.setattr(native_graphics,'load_library',missing)
    try: assert native_render.rgb_image(a,ev=1) is None
    finally: native_render._library.cache_clear()


def test_native_rejects_invalid_arguments_before_writing(application):
    library=native_render._library()
    assert library.cadence_rgb_lut(None,0,0,None,0,0,None,0,10,10,None)==1
    image=QImage(64,64,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
    expected=image.copy(); painter=QPainter(image)
    try:
        assert not native_render.paint_stroke(painter,Mark(points=((float('nan'),.5,1.),)),64,64)
    finally: painter.end()
    assert image==expected


@pytest.mark.parametrize('size',[(157,91),(640,360)])
def test_strokes_erasers_transforms_and_groups_exact(application,monkeypatch,size):
    rng=np.random.default_rng(12)
    points=tuple(map(tuple,rng.random((28,3))))
    for pressure in (False,True):
        for sensitivity in (.1,1,2.7,5):
            mark=Mark(points=points,size=.027,opacity=.63,pressure=pressure,sensitivity=sensitivity,
                transform=(.8,.1,-.05,1.1,.07,-.02))
            eraser=replace(mark,tool='eraser',points=points[::3],size=.04,opacity=.41)
            group=Mark(tool='group',children=(mark,eraser),opacity=.7,transform=(1.,.1,.1,1.,0.,0.))
            for marks in ((mark,),(mark,eraser),(group,)):
                monkeypatch.setenv('CADENCE_NATIVE_RENDER','0'); expected=render_marks(marks,*size)
                monkeypatch.setenv('CADENCE_NATIVE_RENDER','1'); actual=render_marks(marks,*size)
                assert actual==expected


def test_cached_onions_change_at_first_frame_and_after_edit(application,monkeypatch):
    mark=Mark(points=((.3,.3,1),(.7,.7,.5)),size=.07)
    keys=tuple(DrawingKey(i*3,i*3+2,(replace(mark,color=color),)) for i,color in enumerate(('#ff0000','#00ff00','#0000ff')))
    cache=DrawingRasterCache(3*120*70*4)
    for frame in range(12):
        monkeypatch.setenv('CADENCE_NATIVE_RENDER','0'); expected=render_layer(keys,frame,120,70,3,3,1)
        monkeypatch.setenv('CADENCE_NATIVE_RENDER','1'); actual=render_layer(keys,frame,120,70,3,3,1,cache=cache)
        assert actual==expected and cache.bytes<=cache.budget
    edited=(replace(keys[0],marks=(replace(mark,color='#abcdef',opacity=.2),)),)+keys[1:]
    cache.retain(edited)
    assert id(keys[0].marks) not in [key[0] for key in cache.entries]
    assert render_layer(edited,1,120,70,3,3,1,cache=cache)==render_layer(edited,1,120,70,3,3,1)
    cache.retain(())
    assert not cache.entries and cache.bytes==0


def test_cache_lru_and_oversize(application):
    cache=DrawingRasterCache(2*32*16*4)
    marks=[(Mark(points=((i*.1,.5,1),)),) for i in range(3)]
    a=cache.render(marks[0],32,16);cache.render(marks[1],32,16)
    assert cache.render(marks[0],32,16).cacheKey()==a.cacheKey()
    cache.render(marks[2],32,16)
    assert (id(marks[1]),32,16) not in cache.entries
    cache.render(marks[0],192,108)
    assert cache.bytes==cache.budget and len(cache.entries)==2
    cache.clear(); assert cache.bytes==0


def test_state_length_cache_does_not_survive_edit_or_serialize():
    state=State((Segment('a',0,100),))
    assert state.length==100
    edited=replace(state,segments=state.segments+(Segment('b',0,20),))
    assert edited.length==120 and state.length==100 and 'length' not in asdict(state)


def test_viewer_native_and_fallback_modes(application,monkeypatch):
    from widgets import Viewer
    monkeypatch.setenv('CADENCE_RENDERER','software')
    viewer=Viewer(); rng=np.random.default_rng(42)
    viewer.rgb=rng.integers(0,256,(90,161,3),dtype=np.uint8)
    b=rng.integers(0,256,(90,161,3),dtype=np.uint8)
    for reference in (b,b[:60]):
        viewer.reference_rgb=reference
        for mode in ('overlay','difference','horizontal','vertical','front','wipe'):
            for swapped in (False,True):
                viewer.compare_mode=mode;viewer.comparing=True;viewer.ev=.8
                viewer.compare_swapped=swapped;viewer.flip_h=True;viewer.flip_v=True
                monkeypatch.setenv('CADENCE_NATIVE_RENDER','0');viewer._effect_signature=None;viewer.apply_effect()
                expected=viewer.image.copy();wipe=viewer.wipe_image.copy() if viewer.wipe_image else None
                monkeypatch.setenv('CADENCE_NATIVE_RENDER','1');viewer._effect_signature=None;viewer.apply_effect()
                assert viewer.image==expected and viewer.wipe_image==wipe
                identity=viewer.image.cacheKey();viewer.apply_effect();assert viewer.image.cacheKey()==identity
    viewer.close()
