# SPDX-License-Identifier: GPL-3.0-only
import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import av
import numpy as np
import pytest
from media import prepare_media,prepare_batch,run_ffmpeg,export_video,PreviewReader
from model import Document,TimelinePCM,RATE,sample_at,locate
from session import write_snapshot,read_session

@pytest.fixture
def audio_source(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    path=tmp_path/'son seul.wav'
    run_ffmpeg(['-f','lavfi','-i','sine=frequency=440:duration=0.83','-ar','44100',str(path)])
    return path

@pytest.mark.parametrize('extension',['wav','mp3'])
def test_audio_import_edit_export_reload(audio_source,extension,tmp_path):
    path=audio_source
    if extension=='mp3':
        path=tmp_path/'son seul.mp3';run_ffmpeg(['-i',str(audio_source),'-c:a','libmp3lame',str(path)])
    updates=[];m=prepare_media(path,progress=lambda p,message:updates.append(p))
    assert m['has_video'] is False and m['has_audio'] and m['frames']==20 and m['fps']=='24'
    assert Path(m['audio']).stat().st_size==sample_at(20,Fraction(24))*4
    assert np.max(np.load(m['waveform']))>0 and updates[-1]==1
    stamp=Path(m['audio']).stat().st_mtime_ns
    assert prepare_media(path)['id']==m['id'] and Path(m['audio']).stat().st_mtime_ns==stamp
    doc=Document();doc.append_media([m]);assert locate(doc.state.segments,5)[0] is None and locate(doc.state.audio,5)[0]==m['id']
    original=doc.state;doc.select(3,6);doc.cut(True);assert doc.state.length==17
    doc.undo();assert doc.state.segments==original.segments
    doc.state=replace(doc.state,position=20,selection=None);doc.paste(True);assert doc.state.length==23
    doc.undo();doc.duplicate_range(0,20);assert doc.state.length==40;doc.undo()
    pcm=TimelinePCM(doc.state.audio,doc.media,doc.fps)
    try: assert np.max(np.abs(np.frombuffer(pcm.read(0,RATE//2),dtype='<i2')))>1000
    finally: pcm.close()
    output=tmp_path/'audio-noir.mp4';export_video(doc.state,doc.media,doc.fps,output)
    with av.open(str(output)) as c:
        assert c.streams.audio and c.streams.video
        frames=list(c.decode(video=0));assert len(frames)==20 and max(f.to_ndarray(format='rgb24').max() for f in frames)==0
    with av.open(str(output)) as c: assert max(np.abs(f.to_ndarray()).max() for f in c.decode(audio=0))>.01
    saved=tmp_path/'audio.cadence';doc.save(saved);loaded=Document.load(saved)
    assert json.loads(saved.read_text(encoding='utf-8'))['version']==13 and loaded.state==doc.state
    snapshot=tmp_path/'last_session.json';write_snapshot(snapshot,(doc.state,doc.media,doc.fps,doc.review,doc.project_path,False),{})
    assert read_session(snapshot)[1].state==doc.state

def test_audio_with_video_at_project_frame_rate(audio_source,tmp_path):
    video=tmp_path/'clip.mp4';run_ffmpeg(['-f','lavfi','-i','color=c=red:s=160x90:r=30:d=0.5','-c:v','libx264',str(video)])
    items=prepare_batch([video,audio_source]);doc=Document(30);doc.append_media(items)
    assert [m['frames'] for m in items]==[15,25] and doc.state.length==40
    assert locate(doc.state.segments,20)[0] is None and locate(doc.state.audio,20)[0]==items[1]['id']
    output=tmp_path/'mix.mp4';export_video(doc.state,doc.media,doc.fps,output)
    with av.open(str(output)) as c:
        frames=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
        assert len(frames)==40 and frames[0][:,:,0].mean()>200 and frames[15].max()==0

def test_mp3_cover_is_not_imported_as_video(audio_source,tmp_path):
    cover=tmp_path/'cover.png';path=tmp_path/'album.mp3'
    run_ffmpeg(['-f','lavfi','-i','color=c=red:s=32x32','-frames:v','1',str(cover)])
    run_ffmpeg(['-i',str(audio_source),'-i',str(cover),'-map','0:a','-map','1:v','-c:a','libmp3lame','-c:v','png','-disposition:v','attached_pic',str(path)])
    m=prepare_media(path);assert m['has_video'] is False and m['frames']==20

def test_audio_open_path_and_title(audio_source,window,application):
    from PySide6.QtTest import QTest
    import time
    w=window;w.doc.saved_signature=w.doc.signature();errors=[];w.error=errors.append
    w.open_path(str(audio_source));deadline=time.monotonic()+15
    while w.job and time.monotonic()<deadline: application.processEvents();QTest.qWait(20)
    assert w.job is None and not errors and w.doc.state.length==20
    assert w.windowTitle().endswith(audio_source.name) and w.media_info.text()=='Audio'
    assert w.viewer.image is not None and w.rendered_token==w.token

from test_drawing import application,window
