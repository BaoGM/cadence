# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import hashlib
from pathlib import Path
import threading
import zipfile

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from engine import PlaybackSlices, sample_at
from model import Document, Segment, State
from test_drawing import application, window
from update_store import dispatch, read_state, unpack, write_state


def test_compact_tabs_and_real_media_gestures(window,application):
    w=window; timeline=w.timeline
    w.request_frame=lambda:None
    w.doc.state=State(tuple(Segment('a',i,i+10,cut_before=True) for i in (0,10,20)))
    w.refresh(); application.processEvents()
    timeline.simple=False
    assert w.library_tabs.tabBar().compact
    def click(x,modifier=Qt.NoModifier):
        point=QPoint(x,timeline.track_y('video')+8)
        QTest.mouseClick(timeline,Qt.LeftButton,modifier,point)
        QTest.mouseDClick(timeline,Qt.LeftButton,modifier,point)
        QTest.mouseRelease(timeline,Qt.LeftButton,modifier,point)
    click(38); assert w.doc.active_track.info.audio_expanded
    click(38); assert not w.doc.active_track.info.audio_expanded
    click(round(timeline.x_for(3))); click(round(timeline.x_for(24)),Qt.ControlModifier)
    assert w.doc.state.selection_ranges()==((0,10),(20,30))
    click(round(timeline.x_for(24)),Qt.ControlModifier)
    assert w.doc.state.selection_ranges()==((0,10),)
    click(round(timeline.x_for(16)),Qt.ShiftModifier)
    assert w.doc.state.selection==(0,30)
    click(38,Qt.ShiftModifier)
    assert w.doc.state.selection==(0,30) and not w.doc.active_track.info.audio_expanded


def test_discontinuous_edits_and_sample_clock():
    doc=Document()
    doc.state=State(tuple(Segment(key,0,10) for key in 'abc'))
    track=doc.state.track_info.id
    doc.state=replace(doc.state,selection=(0,10),selected_clips=((track,0,10),(track,20,30)))
    assert doc.copy()==20 and [s.media for s in doc.clipboard]==['a','c']
    assert doc.cut()==20 and [s.media for s in doc.state.segments]==['b']
    assert doc.undo() and doc.state.selection_ranges()==((0,10),(20,30))
    class PCM:
        def read(self,start,count):
            return bytes([1 if start<sample_at(10,24) else 3])*count
    clock=PlaybackSlices(PCM(),doc.state.selection_ranges(),24)
    boundary=sample_at(10,24)
    assert clock.read(boundary-2,4)==bytes([1,1,3,3])
    assert clock.frame(boundary)==20 and clock.frame(boundary-1)==9


def test_archive_rejects_escape_and_cancel(tmp_path):
    package=tmp_path/'fixture.zip'; dest=tmp_path/'stage'; dest.mkdir()
    with zipfile.ZipFile(package,'w') as out: out.writestr('Cadence/../outside','a')
    with pytest.raises(ValueError): unpack(package,dest,threading.Event())
    assert not (tmp_path/'outside').exists()


@pytest.mark.parametrize('succeeds',[False,True])
def test_first_start_promotes_or_falls_back(tmp_path,succeeds):
    base=tmp_path/'Cadence.exe'; base.touch()
    store=tmp_path/'.cadence-updates'; store.mkdir()
    for version in ('1.18.6','1.18.7'):
        folder=store/version; folder.mkdir(); (folder/base.name).touch()
    write_state(store,dict(active='1.18.6',pending='1.18.7'))
    calls=[]
    class Child:
        def poll(self): return 0 if succeeds else 1
    def launch(exe,args,ready=None):
        calls.append((exe.parent.name,args))
        if ready and succeeds: ready.touch()
        return Child()
    assert dispatch(base,'1.18.5',['project.cadence'],launch=launch)
    assert read_state(store)['active']==('1.18.7' if succeeds else '1.18.6')
    assert calls[-1][1]==['project.cadence']
    assert len(calls)==(1 if succeeds else 2)
