# SPDX-License-Identifier: GPL-3.0-only
import json
from dataclasses import replace
from pathlib import Path
from fractions import Fraction
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPoint,QEvent,QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMessageBox
from PySide6.QtTest import QTest
from model import Document,State,Segment
from drawing import Mark,DrawingKey
from session import read_session,SessionRecovery
from test_drawing import application,window


def test_session_roundtrip_unsaved_edits_and_view(window,tmp_path):
    w=window; w.request_frame=lambda:None
    path=tmp_path/'original.cadence'; w.doc.save(path); original=path.read_bytes()
    w.doc.media['unused']={**w.doc.media['a'],'id':'unused','name':'unused.mp4'}
    key=DrawingKey(4,7,(Mark(points=((.5,.5,1),)),))
    w.doc.commit('drawing',replace(w.doc.state,position=13,selection=(4,16),drawings=(key,),exposure=2))
    w.timeline.zoom=3; w.timeline.view_start=8; w.timeline.units='frames'
    w.viewer.zoom=1.8; w.viewer.pan=QPointF(30,-20); w.viewer.angle=20
    w.drawing.onion.setChecked(True); w.drawing.before.setValue(8); w.volume.setMuted(True)
    w.session.checkpoint(wait=True)
    payload,restored=read_session(w.session.path)
    assert restored.state==w.doc.state and restored.dirty and restored.project_path==str(path)
    assert set(restored.media)=={'a','unused'} and path.read_bytes()==original
    assert payload['view']['zoom']==1.8 and payload['view']['before']==8
    w.install_doc(restored); w.viewer.reset_view(); w.timeline.reset_view(); w.drawing.onion.setChecked(False)
    w.session.apply_view(payload['view'])
    assert w.viewer.zoom==1.8 and w.viewer.pan==QPointF(30,-20) and w.viewer.angle==20
    assert w.timeline.zoom==3 and w.timeline.view_start==8 and w.timeline.units=='frames'
    assert w.drawing.onion.isChecked() and w.volume.muted
    assert w.doc.state.position==13 and w.doc.dirty and path.read_bytes()==original


def test_blank_start_keeps_previous_session_and_second_instance_cannot_overwrite(window):
    s=window.session; s.checkpoint(wait=True); before=s.path.read_bytes()
    second=SessionRecovery(window)
    try:
        assert not second.owner
        window.doc=Document(); s.checkpoint(wait=True); second.checkpoint(wait=True)
        assert s.path.read_bytes()==before
    finally: second.close()


def test_session_refusal_and_restore_choice(window,monkeypatch):
    w=window; s=w.session; s.checkpoint(wait=True); w.doc=Document()
    from dialogs import ConfirmationDialog
    monkeypatch.setattr(ConfirmationDialog,'exec',lambda box:1)
    restored=[]; monkeypatch.setattr(s,'restore',lambda data,doc:restored.append(doc))
    s.offer(); assert len(restored)==1 and restored[0].state.length==30
    s.pending=False
    monkeypatch.setattr(ConfirmationDialog,'exec',lambda box:2); s.offer()
    assert not s.path.exists() and not s.pending


def test_unreadable_session_reported_without_deletion(window,monkeypatch):
    s=window.session; s.path.write_text('{broken',encoding='utf-8'); window.doc=Document()
    errors=[]; monkeypatch.setattr(window,'error',errors.append); s.offer()
    assert errors and s.path.read_text()=='{broken' and not s.pending


def test_restore_missing_media_keeps_snapshot(window,monkeypatch,application):
    w=window; s=w.session; s.checkpoint(wait=True); payload,doc=read_session(s.path); saved=s.path.read_bytes()
    errors=[]; monkeypatch.setattr(w,'error',errors.append); w.doc=Document(); s.restore(payload,doc)
    for _ in range(300):
        application.processEvents(); QTest.qWait(10)
        if w.job is None: break
    assert w.job is None and errors and not s.pending and not w.doc.media
    assert s.path.read_bytes()==saved


def test_restore_rebuilds_preview_cache_and_exact_frame(window,tmp_path,monkeypatch,application):
    import media
    w=window; s=w.session; w.doc.state=replace(w.doc.state,position=17)
    s.checkpoint(wait=True); payload,doc=read_session(s.path); expected=[]
    monkeypatch.setattr(media,'validate_media',lambda m:None)
    def prepare(path,fps,progress,cancel,quality,cadence=None,defer_audio=False):
        assert cadence is None
        expected.append((path,fps,quality)); return {**doc.media['a'],'proxy':'rebuilt.mp4','id':'fresh'}
    monkeypatch.setattr(media,'prepare_media',prepare); monkeypatch.setattr(w,'request_frame',lambda:None)
    w.doc=Document(); s.restore(payload,doc)
    for _ in range(300):
        application.processEvents(); QTest.qWait(10)
        if w.job is None: break
    assert expected==[('test.mp4',Fraction(24),'native')]
    assert w.doc.state.position==17 and w.doc.media['a']['proxy']=='rebuilt.mp4'
    assert not s.pending


@pytest.mark.parametrize('simple',[True,False])
def test_hover_frames_follow_zoom_without_seek(window,simple,application):
    t=window.timeline; t.simple=simple; t.set_document(window.doc.state,window.doc.media,window.doc.fps)
    t.resize(1000,t.height()); t.zoom=3; t.view_start=10
    old=window.doc.state
    x=t.x_for(14.5); point=QPointF(x,18)
    event=QMouseEvent(QEvent.Type.MouseMove,point,point,Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    application.sendEvent(t,event)
    assert t.hover_frame()==14 and window.doc.state==old
    t.units='time'; assert t.hover_frame()==14
    t.view_start=18; assert t.hover_frame()==22
    t.hover_x=t.track_right(); assert t.hover_frame()==28
    t.hover_x=0; assert t.hover_frame() is None
    application.sendEvent(t,QEvent(QEvent.Type.Leave)); assert t.hover_frame() is None


def test_slow_decoder_is_not_starved_by_playback_ticks(window,monkeypatch):
    w=window; w.token=20; w.rendered_token=19; w.display_frame=0
    requested=[]; monkeypatch.setattr(w.decoder,'request',lambda token,*args:requested.append(token))
    monkeypatch.setattr(w.transport,'running',True); monkeypatch.setattr(w.transport,'clock',lambda:(12,1,False))
    for _ in range(20): w.tick()
    assert w.token==20 and not requested
    w.frame_ready(20,np.zeros((20,30,3),np.uint8)); w.tick()
    assert w.token==21 and requested==[21] and w.doc.state.position==12
    w.seek(3); assert w.token==22 and w.doc.state.position==3
    w.frame_ready(21,np.ones((20,30,3),np.uint8)); assert w.rendered_token==20
    w.frame_ready(22,np.ones((20,30,3),np.uint8)); assert w.rendered_token==22


def test_renderer_preferences_and_swap_interval(window):
    from preferences import defaults,validate,ShortcutDialog,default_renderer
    from video_surface import synchronized_format
    assert synchronized_format().swapInterval()==1
    data=defaults(window.action_registry); assert data['video_renderer']==default_renderer()
    data['video_renderer']='software'; data=validate(data,window.action_registry)
    dialog=ShortcutDialog(window.action_registry,data,window)
    assert dialog.video_renderer.currentData()=='software' and dialog.collect()['video_renderer']=='software'
    assert dialog.general_preferences()['video_renderer']=='software'
    dialog.close()


def test_fullscreen_checkpoint_restores_normal_panels(window,application):
    w=window; s=w.session; before=s.view()
    w.toggle_fullscreen(); application.processEvents()
    try:
        w.doc.state=replace(w.doc.state,position=21); s.checkpoint(wait=True)
        data,doc=read_session(s.path)
        assert doc.state.position==21
        assert data['view']['panels']==before['panels'] and data['view']['layout']==before['layout']
    finally: w.toggle_fullscreen()
