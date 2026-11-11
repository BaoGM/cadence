# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
from fractions import Fraction
import io,time
import numpy as np
from PySide6.QtWidgets import QStyle,QStatusBar
from test_drawing import application,window,pixels
from drawing import DrawingKey,Mark
from drawing_timeline import DRAWING_GOLD
from model import Segment,State
from capture import CaptureDialog

def test_title_panels_metadata_and_context_modes(window,application):
    w=window; w.request_frame=lambda:None
    w.doc.media['b']=dict(w.doc.media['a'],id='b',name='seconde.mov',width=1920,height=1080)
    w.doc.state=State((Segment('a',0,10),Segment('b',0,10)),position=12); w.refresh()
    assert w.windowTitle().endswith('test') and w.media_info.text()=='1920 × 1080 · 24.000 i/s'
    w.doc.project_path='C:/projets/Validation animation.cadence'; w.refresh()
    assert w.windowTitle().endswith('Validation animation')
    assert not {'inspector','meta','status'} & w.panel_widgets().keys()
    assert not {'inspector','meta','status'} & w.workspaces.panels.keys()
    assert not w.findChildren(QStatusBar)
    assert all(not any(part in key for part in ('Afficher les ajustements','Afficher les informations du média','Afficher la barre d’état')) for key in w.action_registry)
    for widget in (w.exp_spin,w.apply_export,w.copy_audio,w.leave_gap,w.link_tracks,w.link_drawings): assert w.header.isAncestorOf(widget)
    assert w.transport_widget.isAncestorOf(w.media_info)
    menu=w.createPopupMenu(); assert menu.actions()[0].data()=='workspace_mode' and menu.actions()[1].isSeparator()
    menu.actions()[0].trigger(); assert w.workspaces.mode=='read' and not w.workspaces.toggle.isChecked()
    menu.deleteLater(); menu=w.createPopupMenu(); menu.actions()[0].trigger(); assert w.workspaces.mode=='edit' and w.workspaces.toggle.isChecked(); menu.deleteLater()
    assert w.viewer.toolTip()==''
    assert w.exp_spin.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay,None,w.exp_spin)==1200
    assert w.exp_spin.style().styleHint(QStyle.StyleHint.SH_ToolTip_FallAsleepDelay,None,w.exp_spin)==0

def test_simple_timeline_marks_preserve_ranges_and_empty_keys(window,application):
    w=window; w.request_frame=lambda:None; marks=(Mark(points=((.2,.3,1),)),)
    keys=(DrawingKey(0,1,marks),DrawingKey(5,10,marks),DrawingKey(15,17,()))
    w.doc.state=replace(w.doc.state,drawings=keys,position=29); w.refresh(); w.workspaces.switch('read'); application.processEvents()
    t=w.timeline; rects=list(t.drawing_track.simple_markers()); assert len(rects)==2
    image=t.grab().toImage()
    y=round(rects[0].center().y())
    assert image.pixelColor(round(t.x_for(7)),y)==DRAWING_GOLD
    assert image.pixelColor(round(t.x_for(16)),y)!=DRAWING_GOLD
    t.zoom=3; t.view_start=7; t.clamp_view(); rects=list(t.drawing_track.simple_markers())
    assert len(rects)==1 and rects[0].left()==t.track_left() and abs(rects[0].right()-t.x_for(10))<.01
    assert w.doc.state.drawings==keys

def test_capture_cue_waits_for_recorded_frame(window,monkeypatch):
    import capture
    d=CaptureDialog(window); events=[]
    monkeypatch.setattr(capture,'start_sound',lambda:events.append('sound'))
    monkeypatch.setattr(d.feedback,'recording',lambda screen:events.append('recording'))
    monkeypatch.setattr(d.feedback,'countdown',lambda screen,n:events.append(n))
    class Proc:
        def poll(self): return None
    d.countdown=3; d.deadline=time.monotonic()+2.8; d.tick(); assert events==[3]
    d.countdown=0; d.proc=Proc(); d.tick(); assert events==[3]
    stream=io.BytesIO(b'frame=0\nprogress=continue\nframe=1\nprogress=continue\n'); d.read_progress(stream)
    assert stream.closed and d.record_ready.is_set()
    d.tick(); d.tick(); assert events==[3,'recording','sound'] and d.start_notified
    d.proc=None; d.reject(); d.deleteLater()
