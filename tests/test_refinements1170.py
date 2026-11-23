# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import numpy as np
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from model import Document,Segment,locate
from test_tracks1170 import two_tracks
from test_render1170 import clips,application,document


def test_audio_flag_is_independent_persistent_and_undoable(tmp_path):
    doc,first,second=two_tracks()
    original=doc.state
    doc.enable_track_audio(first,False)
    assert all(s.muted for s in doc.state.tracks[0].audible)
    assert not any(s.muted for s in doc.state.tracks[1].audible)
    assert doc.state.tracks[0].audio==original.tracks[0].audio
    path=tmp_path/'muted.cadence'; doc.save(path)
    assert Document.load(path).state==doc.state
    doc.undo(); assert doc.state==original
    doc.remove_media_track(second); doc.enable_track_audio(first,False)
    assert doc.format_version()==16
    doc.save(path); assert not Document.load(path).state.track_info.audio_enabled


def test_track_names_migrate_and_zero_selection_is_respected():
    doc,first,second=two_tracks()
    assert [t.info.name for t in doc.state.tracks]==['Piste 1','Piste 2']
    data=doc.to_data(); data['state']['track_info']['name']='Média 1'
    assert Document.from_data(data).state.track_info.name=='Piste 1'
    doc.select_track(second,extend=True)
    assert doc.selected_track_ids==()
    old=doc.state; doc.select(0,5); doc.delete()
    assert doc.state.tracks==old.tracks
    doc.select_track(first,extend=True); assert doc.selected_track_ids==(first,)


def test_cross_track_move_and_copy_preserve_pairing_and_undo():
    doc,first,second=two_tracks(40,20)
    doc.select_track(first,extend=True)
    old=doc.state
    assert doc.transfer_media(first,second,10,20,30)
    upper,lower=doc.state.tracks
    assert locate(upper.segments,10)==locate(upper.audio,10)==('a',20) and upper.length==30
    assert locate(lower.segments,20)[0] is None
    assert locate(lower.segments,30)==locate(lower.audio,30)==('a',10)
    assert doc.undo() and doc.state==old
    assert doc.transfer_media(first,second,10,20,0,True)
    assert doc.state.tracks[0]==old.tracks[0]
    assert locate(doc.state.tracks[1].segments,10)==('b',0)


def test_disabled_track_audio_in_playback_and_export(clips,tmp_path):
    import av
    from composite_media import MixedPCM
    from model import TimelinePCM
    from media import export_video
    doc=document(clips)
    doc.enable_track_audio(doc.state.track_info.id,False)
    pcm=TimelinePCM(doc.state.second_track.audio,doc.media,doc.fps)
    mixed=MixedPCM(doc.state,doc.media,doc.fps)
    try:
        expected=pcm.read(0,96000)
        assert mixed.read(0,96000)==expected
    finally: pcm.close(); mixed.close()
    path=tmp_path/'one-track.wav'; export_video(doc.state,doc.media,doc.fps,path)
    with av.open(str(path)) as source:
        actual=np.concatenate([frame.to_ndarray().reshape(-1) for frame in source.decode(audio=0)])
    assert np.array_equal(actual,np.frombuffer(expected,dtype='<i2'))


def test_track_body_selection_doubleclick_drag_and_audio_menu(application,clips,tmp_path,monkeypatch):
    from app import MainWindow
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json'))
    window=MainWindow(); window.workspaces.switch('edit'); window.show()
    doc=document(clips); window.install_doc(doc)
    timeline=window.timeline
    first,second=(t.info.id for t in doc.state.tracks)
    try:
        x=round(timeline.x_for(10))
        QTest.mouseClick(timeline,Qt.LeftButton,Qt.ControlModifier,QPoint(x,55))
        assert set(doc.selected_track_ids)=={first,second}
        QTest.mouseClick(timeline,Qt.LeftButton,Qt.ControlModifier,QPoint(x,88))
        assert doc.selected_track_ids==(first,)
        QTest.mouseClick(timeline,Qt.LeftButton,Qt.ControlModifier,QPoint(x,88))
        QTest.mouseDClick(timeline,Qt.LeftButton,Qt.NoModifier,QPoint(x,88))
        assert doc.state.selection==(0,48) and doc.selected_track_ids==(second,)
        assert not doc.state.second_track.info.audio_expanded
        QTest.mouseDClick(timeline,Qt.LeftButton,Qt.ShiftModifier,QPoint(40,88))
        assert not doc.state.second_track.info.audio_expanded
        doc.select_track(first); doc.select_track(second,extend=True); window.refresh()
        original=doc.state
        QTest.mousePress(timeline,Qt.LeftButton,Qt.NoModifier,QPoint(x,55))
        event=QMouseEvent(QEvent.MouseMove,QPointF(x,88),QPointF(timeline.mapToGlobal(QPoint(x,88))),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(timeline,event)
        QTest.mouseRelease(timeline,Qt.LeftButton,Qt.NoModifier,QPoint(x,88))
        assert all(s.media is None for s in doc.state.tracks[0].segments)
        assert doc.state.second_track.length==96
        assert doc.undo() and doc.state.tracks==original.tracks
        window.refresh()
        menu=timeline.context_menu(QPoint(x,55))
        next(a for a in menu.actions() if a.data()=='track_audio').trigger()
        assert not doc.state.track_info.audio_enabled
        menu.deleteLater()
        timeline.simple=True; timeline.set_document(doc.state,doc.media,doc.fps)
        assert timeline.track_y('drawing')>25
        assert timeline.track_y('drawing')+4<timeline.simple_track_rect().top()
        assert timeline.height()>=timeline.simple_track_rect().bottom()+4
    finally:
        doc.saved_signature=doc.signature(); window.close(); application.processEvents()


def test_cancel_dialog_waits_for_host_acknowledgement(application):
    from drawing_progress import DrawingProgress
    called=[]
    dialog=DrawingProgress(None,lambda:called.append(True) or True)
    dialog.show(); dialog.reject()
    assert dialog.isVisible() and called==[True] and not dialog.cancel_button.isEnabled()
    dialog.reject(); assert called==[True]
    dialog.done(0); dialog.deleteLater()


def test_platform_release_tag_does_not_select_linux():
    from updates import select_release
    def release(tag):
        return dict(tag_name=tag,assets=[dict(name='Cadence-1.17.0-'+suffix,state='uploaded',size=42)
            for suffix in ('Windows.zip','update.json')])
    selected=select_release([release('v1.18.0-linux'),release('v1.17.0-windows')],'1.16.1',False)
    assert selected.version=='1.17.0'
    assert '/v1.17.0-windows/' in selected.url


def test_bridge_keeps_a_slow_drawing_step_connected():
    import socket
    from integrations.cadence_bridge import Bridge,monotonic
    server,client=socket.socketpair()
    server.setblocking(False); client.setblocking(False)
    bridge=Bridge('maya',lambda:dict(frame=1,start=1,end=100,fps=24),lambda frame:None)
    bridge.sock=client; bridge.authenticated=True; bridge.received=monotonic()-6
    def job():
        while True: yield dict(progress=50)
    bridge.drawing_job=job(); bridge.drawing_request='test'
    try:
        bridge.tick()
        assert bridge.sock is client and bridge.drawing_job is not None
    finally:
        bridge.close(); server.close()
