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
    w=window; w.header.show(); w.library.show(); application.processEvents()
    w.workspaces.switch('read'); application.processEvents()
    assert w.timeline.simple and w.timeline.height()==44
    assert w.timeline.x_for(0)==w.timeline.width()-w.timeline.x_for(w.doc.state.length)
    assert w.timeline.frame_for(w.timeline.x_for(0))==0
    assert w.timeline.frame_for(w.timeline.x_for(w.doc.state.length))==w.doc.state.length-1
    assert w.header.isHidden() and w.library.isHidden() and w.header.isHidden()
    assert not w.timecode_overlay.isHidden() and not w.transport_widget.isHidden()
    w.workspaces.switch('edit'); application.processEvents()
    assert not w.timeline.simple and not w.header.isHidden() and not w.library.isHidden()

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
    assert 'palettegen=stats_mode=single' in args[args.index('-filter_complex')+1]
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
