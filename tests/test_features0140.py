# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
from fractions import Fraction
import subprocess
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QFileDialog,QDialog
from test_drawing import application,window,pixels,screen_point
from clip_geometry import apply_geometry,IDENTITY
from model import Segment,State,Document,compact
from media import ffmpeg,prepare_media,export_video

def test_geometry_pixels_roundtrip_undo(application,tmp_path):
    rgb=np.zeros((100,200,3),np.uint8); rgb[:,:100,0]=255; rgb[:,100:,2]=255
    seg=Segment('a',0,10,crop=(.5,0,.5,1),placement=(.25,.25,.5,.5))
    out=apply_geometry(rgb,seg,2)
    assert out[50,100,2]==255 and out[5,5].max()==0 and out[50,100,0]==0
    d=Document(); d.media={'a':{'id':'a','frames':10}}; d.state=State((Segment('a',0,10),)); old=d.state
    d.commit('transform',replace(d.state,segments=(seg,))); d.save(tmp_path/'geometry.cadence')
    assert Document.load(tmp_path/'geometry.cadence').state==d.state
    d.undo(); assert d.state==old
    d.redo(); assert d.state.segments==(seg,)
    assert len(compact((Segment('a',0,5),Segment('a',5,10,crop=(0,0,.5,1)))))==2

def test_handles_commit_cancel_and_shortcuts(window,application):
    from PySide6.QtTest import QTest
    w=window; g=w.clip_tools; w.request_frame=lambda:None
    w.activateWindow(); w.viewer.setFocus(); application.processEvents()
    QTest.keyClick(w.viewer,Qt.Key.Key_T,Qt.KeyboardModifier.ControlModifier); assert g.mode=='resize'
    def event(kind,pt,button):
        pos=screen_point(w.drawing,*pt); e=QMouseEvent(kind,pos,pos,button,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier); QApplication.sendEvent(w.viewer,e)
    event(QEvent.Type.MouseButtonPress,(1,1),Qt.MouseButton.LeftButton)
    event(QEvent.Type.MouseMove,(.6,.6),Qt.MouseButton.NoButton)
    event(QEvent.Type.MouseButtonRelease,(.6,.6),Qt.MouseButton.LeftButton)
    assert g.pending.placement[2:]==pytest.approx((.6,.6),abs=.01)
    assert w.doc.state.segments[0].placement==IDENTITY
    QTest.keyClick(w.viewer,Qt.Key.Key_Return); assert w.doc.state.segments[0].placement[2]==pytest.approx(.6,abs=.01)
    w.undo(); assert w.doc.state.segments[0].placement==IDENTITY
    QTest.keyClick(w.viewer,Qt.Key.Key_C,Qt.KeyboardModifier.AltModifier); assert g.mode=='crop'
    QTest.keyClick(w.viewer,Qt.Key.Key_Escape); assert g.mode is None

def test_reading_mode_restores_panels(window,application):
    w=window; w.library.show(); application.processEvents()
    w.workspaces.switch('read'); application.processEvents()
    assert w.timeline.simple and w.timeline.height()==42
    assert w.timeline.x_for(0)==w.timeline.track_left()
    assert w.timeline.x_for(w.doc.state.length)==w.timeline.track_right()
    assert w.timeline.frame_for(w.timeline.x_for(0))==0
    assert w.timeline.frame_for(w.timeline.x_for(w.doc.state.length))==w.doc.state.length-1
    assert w.studio.file_group.isHidden() and w.library.isHidden() and w.edit_toolbar.isHidden()
    assert w.timecode_overlay.isHidden() and not w.transport_widget.isHidden()
    w.workspaces.switch('edit'); application.processEvents()
    assert not w.timeline.simple and not w.studio.file_group.isHidden() and not w.library.isHidden()

def test_capture_temp_and_gif_without_file_dialog(window,tmp_path,monkeypatch):
    import capture
    monkeypatch.setattr(capture.tempfile,'gettempdir',lambda:str(tmp_path))
    monkeypatch.setattr(capture,'physical_region',lambda *a:(0,0,320,180))
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:pytest.fail('Unexpected save dialog'))
    d=capture.CaptureDialog(window); d.folder.clear(); d.format.setCurrentText('GIF')
    monkeypatch.setattr(d.hotkey,'register',lambda:True)
    d.begin(); assert d.path.parent==tmp_path/'Cadence' and d.path.suffix=='.gif'
    assert d.countdown==3
    args=capture.capture_args((0,0,320,180),24,True,d.path)
    assert args[args.index('-c:v')+1]=='libx264rgb'
    assert args[args.index('-crf')+1]=='0' and args[-1]==str(capture.gif_recording_path(d.path))
    d.reject()

def test_export_geometry_and_gif(application,tmp_path):
    import av
    source=tmp_path/'source.mp4'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=red:s=160x90:r=12:d=1','-c:v','libx264',str(source)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    m=prepare_media(source); seg=Segment(m['id'],0,12,placement=(.25,.25,.5,.5)); st=State((seg,))
    out=tmp_path/'resized.mp4'; export_video(st,{m['id']:m},Fraction(12),out)
    with av.open(str(out)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert len(frames)==12 and frames[0][45,80,0]>200 and frames[0][3,3].max()<20
    gif=tmp_path/'resized.gif'; export_video(st,{m['id']:m},Fraction(12),gif)
    with av.open(str(gif)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert frames and frames[0][45,80,0]>180 and frames[0][3,3].max()<30
    imported=prepare_media(gif); assert imported['frames']>0


@pytest.mark.parametrize('use_proxy',[False,True],ids=['open-source','cached-preview'])
def test_offline_gif_keeps_video_after_source_deletion(tmp_path,monkeypatch,use_proxy):
    import av
    from export_sources import SessionVideoSources
    from media import run_ffmpeg
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    source=tmp_path/('source.mkv' if use_proxy else 'source.mp4')
    run_ffmpeg(['-f','lavfi','-i','testsrc2=s=80x60:r=10:d=1','-f','lavfi','-i','sine=d=1',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)])
    item=prepare_media(source,defer_audio=True)
    key=item['id']
    state=State((Segment(key,2,9),))
    retained=SessionVideoSources()
    try:
        if not use_proxy:
            assert Path(item['proxy'])==source
            retained.retain([item])
        original=tmp_path/'reference.gif'
        export_video(state,{key:item},Fraction(10),original)
        source.unlink()
        Path(item['audio']).unlink()
        destination=tmp_path/'offline.gif'
        export_video(state,{key:item},Fraction(10),destination,retained=retained)
        def decode(path):
            with av.open(str(path)) as container:
                assert not container.streams.audio
                return [frame.to_ndarray(format='rgb24') for frame in container.decode(video=0)]
        expected=decode(original)
        actual=decode(destination)
        assert len(actual)==len(expected)==7
        assert max(np.abs(a.astype(int)-b).mean() for a,b in zip(actual,expected)) < (16 if use_proxy else .01)
        assert not np.array_equal(actual[0],actual[-1])
        if not use_proxy:
            retained.close()
            preserved=destination.read_bytes()
            with pytest.raises(FileNotFoundError,match='Média source introuvable'):
                export_video(state,{key:item},Fraction(10),destination,retained=retained)
            assert destination.read_bytes()==preserved
        assert not list(tmp_path.glob('*.partial.gif'))
    finally:
        retained.close()


def test_window_gif_after_loaded_mp4_removed(window,tmp_path,monkeypatch):
    import av
    import time
    import weakref
    import export_sources
    from PySide6.QtTest import QTest
    from media import run_ffmpeg
    source=tmp_path/'plan.mp4'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=s=80x60:r=10:d=1','-c:v','libx264',str(source)])
    streams=[]
    open_shared=export_sources.open_shared
    def observe_source(path):
        stream=open_shared(path)
        if Path(path)==source: streams.append(weakref.ref(stream))
        return stream
    monkeypatch.setattr(export_sources,'open_shared',observe_source)
    completed=[]
    errors=[]
    monkeypatch.setattr(window,'confirm_discard',lambda:True)
    monkeypatch.setattr(window,'export_done',completed.append)
    monkeypatch.setattr(window,'error',errors.append)
    def await_job(done):
        until=time.monotonic()+12
        while not done() and time.monotonic()<until:
            QTest.qWait(15)
            time.sleep(.005)
        assert done(),errors
    window.open_path(str(source))
    await_job(lambda:window.job is None and window.display_frame==0 and window.rendered_token==window.token)
    original=source.read_bytes()
    source.unlink()
    output=tmp_path/'plan.gif'
    window.start_export(str(output))
    await_job(lambda:window.job is None)
    assert not errors and completed==[str(output)]
    with av.open(str(output)) as container:
        assert sum(1 for _ in container.decode(video=0))==10
    def source_open():
        return any((file:=stream()) is not None and not file.closed for stream in streams)
    assert source_open()
    window.new_project()
    await_job(lambda:not source_open())
    assert not window.doc.media and window.isVisible()
    with source.open('xb') as replacement: replacement.write(original)
    window.open_path(str(source))
    await_job(lambda:window.job is None and window.display_frame==0 and window.rendered_token==window.token)
