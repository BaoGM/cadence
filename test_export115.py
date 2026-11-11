# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
import av
from drawing import Mark,DrawingKey
from model import State,Segment
from media import prepare_media,export_video,run_ffmpeg
from test_drawing import application,window

def test_onion_export_pixels(application,tmp_path):
    source=tmp_path/'black.mp4'
    run_ffmpeg(['-f','lavfi','-i','color=black:s=160x90:r=12:d=1','-c:v','libx264',str(source)])
    m=prepare_media(source)
    state=State((Segment(m['id'],0,12),),drawings=(DrawingKey(5,6,(Mark(points=((.5,.5,1),),size=.3,color='#20ff60',pressure=False),)),))
    out=tmp_path/'onion.mp4'; export_video(state,{m['id']:m},Fraction(12),out,onion=(2,2,1.))
    with av.open(str(out)) as c: frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
    assert len(frames)==12
    assert frames[4][45,80,1]>frames[4][45,80,0]+40
    assert frames[6][45,80,1]>frames[6][45,80,0]+40
    assert frames[3][45,80,1]<frames[4][45,80,1]
    assert frames[2][45,80].max()<20

def test_desktop_and_export_folder(window,application,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtCore import QStandardPaths,QUrl
    from PySide6.QtGui import QDesktopServices
    dialog=QFileDialog(window); dialog.show(); application.processEvents()
    assert QUrl.fromLocalFile(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)) in dialog.sidebarUrls()
    dialog.close()
    seen=[]; monkeypatch.setattr(QDesktopServices,'openUrl',lambda url:seen.append(url))
    window.export_done(str(tmp_path/'movie.mp4'))
    assert seen==[QUrl.fromLocalFile(str(tmp_path))]
