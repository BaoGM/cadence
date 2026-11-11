# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
from fractions import Fraction
from dataclasses import replace
import time,threading,json
import av,numpy as np,pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QMessageBox
from test_drawing import application,window,pixels
from media import prepare_media,PreviewReader,run_ffmpeg,Cancelled

@pytest.mark.parametrize('extension,codec',[('mov','libx264'),('avi','mjpeg')])
def test_direct_precise_random_and_sequential(tmp_path,monkeypatch,extension,codec):
 monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
 path=tmp_path/('source.'+extension)
 run_ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=3','-c:v',codec,*(['-g','40','-bf','3'] if codec=='libx264' else []),str(path)])
 m=prepare_media(path);assert 'direct_start' in m and m['frames']==90
 assert not list((tmp_path/'cache').rglob('preview.avi'))
 with av.open(str(path)) as c: expected=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
 reader=PreviewReader(budget=1)
 try:
  for i in [0,89,40,41,42,10,11,0,88,89]: assert np.array_equal(reader.read(m,i),expected[i])
 finally: reader.close()
 converted=prepare_media(path,Fraction(24));assert 'direct_start' in converted and converted['frames']==72 and converted['direct_frames']==90
 assert not list((tmp_path/'cache').rglob('preview.avi'))


def test_external_avi_open_without_warning(window,application,tmp_path,monkeypatch):
 monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
 path=tmp_path/'Maya playblast.avi';run_ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=1','-c:v','mjpeg',str(path)])
 warnings=[];monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:warnings.append(a))
 window.doc.saved_signature=window.doc.signature();window.open_path(str(path))
 deadline=time.monotonic()+15
 while (window.job or window.rendered_token!=window.token) and time.monotonic()<deadline: application.processEvents();time.sleep(.01)
 assert window.job is None and window.doc.state.length==24 and window.rendered_token==window.token
 assert not warnings


def test_error_with_no_message_is_identified(application):
 from engine import Task
 def fail(progress,cancel): raise RuntimeError()
 task=Task(fail);messages=[];task.failed.connect(messages.append);task.start()
 deadline=time.monotonic()+5
 while not messages and time.monotonic()<deadline:application.processEvents();time.sleep(.01)
 task.wait();assert messages==['RuntimeError'];task.deleteLater()


def test_playback_settings_independent_of_media(window):
 from playback_preferences import save,load,path
 w=window;w.volume.setValue(37);w.volume.setMuted(True);w.timeline.set_units('frames');save(w)
 assert json.loads(path().read_text())==dict(volume=37,muted=True,units='frames',key_step=False,timecode_position=[.5,1.],timecode_locked=False)
 w.volume.setValue(80);w.volume.setMuted(False);w.timeline.set_units('time');load(w)
 assert w.volume.value()==37 and w.volume.muted and w.timeline.units=='frames'
 assert w.transport.volume==0
 w.volume.setMuted(False);assert w.transport.volume==.37

@pytest.mark.parametrize('simple',[True,False])
def test_current_frame_is_visible_without_hover(window,simple):
 w=window;w.workspaces.set_timeline_simple(simple);w.doc.state=replace(w.doc.state,position=8);w.refresh();t=w.timeline;t.hover_x=None
 image=QImage(t.size(),QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
 p=QPainter(image);t.paint_current_highlight(p);t.paint_frame_indicator(p);p.end();rgba=pixels(image)
 y=32 if simple else 60;x=int(t.x_for(8))+1
 assert rgba[y,x,3]>48 and rgba[:30,:,3].max()>0
