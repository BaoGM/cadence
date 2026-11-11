# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import QSize,Qt
from PySide6.QtGui import QImage,QPainter
from drawing import Mark,DrawingKey
from model import Document
from test_drawing import application,window,pixels


def test_onion_playback_matches_paused_and_fades(window,monkeypatch):
    w=window; d=w.drawing
    marks=(Mark(points=((.5,.5,1.),),size=.2,color='#20ff60',pressure=False),)
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(5,6,marks),))
    d.onion.setChecked(True); d.before.setValue(3); d.after.setValue(3); d.ghost.setValue(80)
    def paint(frame,running):
        w.doc.state=replace(w.doc.state,position=frame)
        with monkeypatch.context() as m:
            m.setattr(w.transport,'running',running)
            image=QImage(640,360,QImage.Format.Format_ARGB32_Premultiplied); image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image); painter.translate(320,180)
            try: d.paint(painter,QSize(640,360))
            finally: painter.end()
        return pixels(image)
    for frame in (2,3,4,5,6,7,8):
        paused=paint(frame,False); playing=paint(frame,True)
        assert np.array_equal(paused,playing) and playing[180,320,3]>0
        assert playing[180,320,1]>playing[180,320,0]
    assert paint(6,True)[180,320,3]>paint(7,True)[180,320,3]>paint(8,True)[180,320,3]
    d.onion.setChecked(False); assert paint(6,True)[:,:,3].max()==0


@pytest.mark.parametrize('ev',[-10,10])
def test_exposure_extremes_saved_reopened_and_undo(window,tmp_path,ev):
    w=window; w.request_frame=lambda:None
    w.exp_spin.setValue(ev); w.commit_exposure()
    assert w.doc.state.exposure==ev and w.exp_spin.value()==ev
    path=tmp_path/'exposure.cadence'; w.doc.save(path)
    assert Document.load(path).state.exposure==ev
    w.undo(); assert w.doc.state.exposure==0 and w.exp_spin.value()==0
    w.redo(); assert w.doc.state.exposure==ev and w.exp_spin.value()==ev
