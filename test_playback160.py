# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from types import SimpleNamespace
import threading
import numpy as np
import pytest
from media import PreviewReader,DecodeSuperseded,prefetch_frames,frame_cache_key
from cache_ram import FrameCache
from test_drawing import application,window


def fake_video(monkeypatch):
    import av
    converted=[]; seeks=[]; decoded=[]
    class Frame:
        time_base=Fraction(1,24)
        width=8; height=4
        def __init__(self,index): self.pts=index
        def to_ndarray(self,**kwargs):
            converted.append(self.pts)
            return np.full((4,8,3),self.pts%256,np.uint8)
    class Container:
        streams=SimpleNamespace(video=[SimpleNamespace(time_base=Fraction(1,24))])
        def seek(self,ts,**kwargs): seeks.append(ts); self.start=ts//100*100
        def decode(self,**kwargs):
            for index in range(self.start,1000):
                decoded.append(index); yield Frame(index)
        def close(self): pass
    monkeypatch.setattr(av,'open',lambda path:Container())
    return dict(proxy='fake',fps='24'),converted,seeks,decoded


def test_seek_converts_only_requested_image(monkeypatch):
    media,converted,seeks,decoded=fake_video(monkeypatch)
    reader=PreviewReader(budget=10000)
    try:
        assert np.all(reader.read(media,97)==97)
        assert converted==[97] and decoded==list(range(98))
        assert np.all(reader.read(media,96)==96)
        assert converted==[97,96] and seeks==[97,96]
    finally: reader.close()


def test_interrupted_decode_resumes_without_losing_frame_or_seeking(monkeypatch):
    media,converted,seeks,decoded=fake_video(monkeypatch)
    reader=PreviewReader(budget=10000)
    try:
        with pytest.raises(DecodeSuperseded): reader.read(media,97,lambda:len(decoded)==4)
        assert converted==[] and decoded==[0,1,2,3]
        for _ in range(500):
            with pytest.raises(DecodeSuperseded): reader.read(media,98,lambda:True)
        assert seeks==[97] and decoded==[0,1,2,3]
        assert np.all(reader.read(media,98)==98)
        assert converted==[98] and seeks==[97]
        assert np.all(reader.read(media,99)==99)
        assert seeks==[97]
    finally: reader.close()
    assert not reader.pending and not reader.targets


def test_backward_seek_after_interruption_is_exact(monkeypatch):
    media,converted,seeks,decoded=fake_video(monkeypatch)
    reader=PreviewReader(budget=10000)
    try:
        reader.read(media,180)
        with pytest.raises(DecodeSuperseded): reader.read(media,181,lambda:True)
        assert np.all(reader.read(media,120)==120)
        assert seeks==[180,120] and converted==[180,120]
    finally: reader.close()


def test_playback_prefetch_stays_forward_and_bounded():
    media=dict(proxy_width=3840,proxy_height=2160)
    targets=prefetch_frames(media,70,0,100,1024**3,backward=False)
    assert targets and all(70<i<100 for _,i in targets)
    assert len(targets)<=1024**3//(3840*2160*3)//4
    assert any(i<70 for _,i in prefetch_frames(media,70,0,100,1024**3))


def test_legacy_acceleration_migrates_but_explicit_backends_remain():
    from preferences import preferred_renderer,default_renderer
    assert preferred_renderer({})==default_renderer()
    assert preferred_renderer({'video_renderer':'opengl'})==default_renderer()
    assert preferred_renderer({'video_renderer':'software'})=='software'
    for backend in ('opengl','direct3d','software'):
        assert preferred_renderer({'video_renderer':backend,'video_renderer_version':2})==backend


def test_cached_frame_is_delivered_without_waiting_for_prefetch(monkeypatch):
    import engine
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QApplication
    application=QApplication.instance() or QApplication([])
    started=threading.Event(); release=threading.Event()
    class Reader:
        def __init__(self,**kwargs): pass
        def read(self,media,index,cancel=None):
            started.set(); assert release.wait(5)
            return np.zeros((4,8,3),np.uint8)
        def close(self): pass
    monkeypatch.setattr(engine,'PreviewReader',Reader)
    parent=QObject(); parent.frame_cache=FrameCache(10000)
    media=dict(proxy='fake',fps='24'); cached=np.ones((4,8,3),np.uint8)
    parent.frame_cache.put(frame_cache_key(media,4),cached)
    worker=engine.Decoder(parent); shown=[]
    worker.ready.connect(lambda token,arr:shown.append((token,arr)))
    worker.start()
    try:
        worker.request(1,media,1)
        assert started.wait(2)
        worker.request(2,media,4)
        assert len(shown)==1 and shown[0][0]==2 and shown[0][1] is cached
    finally: release.set(); worker.stop()


@pytest.mark.parametrize('position,ghosts,visible',[(0,False,False),(1,False,False),(8,True,False),(9,True,True),(10,False,True),(12,True,True),(13,True,False)])
def test_video_only_allocates_visible_drawing_layers(window,application,monkeypatch,position,ghosts,visible):
    import draw_ui
    from dataclasses import replace
    from drawing import DrawingKey,Mark
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtCore import QSize
    rendered=[]
    def render(*args,**kwargs):
        rendered.append(args[1])
        image=QImage(args[2],args[3],QImage.Format.Format_ARGB32_Premultiplied)
        return ((0,0),image) if kwargs.get('region') else image
    monkeypatch.setattr(draw_ui,'render_layer',render)
    window.drawing.visible.setChecked(True)
    window.drawing.onion.setChecked(ghosts)
    window.drawing.before.setValue(1); window.drawing.after.setValue(1)
    keys=() if position==0 else (DrawingKey(10,12,(Mark(points=((.5,.5,1),)),)),)
    window.doc.state=replace(window.doc.state,position=position,drawings=keys)
    image=QImage(320,180,QImage.Format.Format_ARGB32_Premultiplied)
    painter=QPainter(image)
    try: window.drawing.paint(painter,QSize(320,180))
    finally: painter.end()
    assert rendered==([position] if visible else [])
    assert (window.drawing.cache is not None)==visible
