# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace,asdict
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt,QPoint,QTimer,QEvent
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication,QMenu,QDialog
from test_drawing import application,window,pixels,screen_point
from drawing import Mark,DrawingKey,render_marks,move_erased_selection,load_keys,translate_mark
from model import Document,State,Segment
from capture import CaptureDialog

def test_read_mode_context_menu_anywhere(window,application,monkeypatch):
    w=window; w.workspaces.switch('read'); application.processEvents(); titles=[]
    def choose():
        menu=QApplication.activePopupWidget()
        titles.extend(a.text() for a in menu.actions()); menu.actions()[1].trigger(); menu.close()
    QTimer.singleShot(50,choose)
    event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,QPoint(160,42),QPoint(160,42))
    QApplication.sendEvent(w.timeline,event)
    assert titles[:2]==['Code temporel','Images'] and 'Supprimer les clés' in titles and w.timeline.units=='frames'

def test_toolbar_action_can_hide_and_show(window,application):
    w=window; w.edit_toolbar.show(); application.processEvents()
    w.toolbar_action.trigger(); application.processEvents(); assert w.edit_toolbar.isHidden()
    w.toolbar_action.trigger(); application.processEvents(); assert not w.edit_toolbar.isHidden()

def test_quick_capture_never_shows_settings(window,application,monkeypatch):
    d=CaptureDialog(window); shown=[]; events=[]
    d.showEvent=lambda e:shown.append(True)
    def begin(): d.armed=True; events.append('start'); QTimer.singleShot(10,d.reject)
    monkeypatch.setattr(d,'begin',begin)
    assert d.run(quick=True)==QDialog.DialogCode.Rejected
    assert events==['start'] and not shown and d.isHidden()
    d.quick=True; d.restore(); assert d.isHidden()

def test_soft_erased_selection_keeps_pixels(application,tmp_path):
    a=Mark(points=((.1,.2,1),(.4,.2,1)),size=.12,color='#ff0000',opacity=.6,pressure=False)
    b=replace(a,points=((.2,.22,1),(.4,.22,1)),color='#00ff00')
    eraser=Mark(tool='eraser',points=((.3,.2,1),),size=.16,opacity=.5,pressure=False)
    original=(a,b,eraser)
    old=pixels(render_marks(original,200,200))
    moved,indices=move_erased_selection(original,(0,1),0,.4)
    new=pixels(render_marks(moved,200,200))
    assert np.max(np.abs(old[:80].astype(int)-new[80:160].astype(int)))<=1
    assert not new[:60,:,3].any()
    keys=load_keys([asdict(DrawingKey(0,1,moved))]); assert keys[0].marks==moved
    doc=Document(); doc.media={'a':{'id':'a','frames':1}}; doc.state=State((Segment('a',0,1),),drawings=keys)
    doc.save(tmp_path/'erased.cadence'); assert Document.load(tmp_path/'erased.cadence').state.drawings==keys
    moved2,_=move_erased_selection(moved,indices,0,-.4)
    assert np.array_equal(pixels(render_marks(moved2,200,200)),old)

def test_eraser_does_not_move_or_erase_unselected_ink(application):
    a=Mark(points=((.1,.2,1),(.4,.2,1)),size=.08,pressure=False)
    b=replace(a,points=((.1,.7,1),(.4,.7,1)),color='#00ff00')
    e=Mark(tool='eraser',points=((.3,.15,1),(.3,.8,1)),size=.08,pressure=False)
    marks=(a,b,e); before=pixels(render_marks(marks,200,200))
    moved,_=move_erased_selection(marks,(0,),.3,0)
    after=pixels(render_marks(moved,200,200))
    assert np.array_equal(before[120:180],after[120:180])
    assert after[40,120,3]==0 and after[40,90,3]>0

def test_lasso_follows_erasure_outside_lasso_and_undo(window,application):
    w=window; d=w.drawing; w.request_frame=lambda:None
    a=Mark(points=((.1,.3,1),(.5,.3,1)),size=.05,pressure=False)
    e=Mark(tool='eraser',points=((.45,.3,1),),size=.08,pressure=False)
    key=DrawingKey(0,1,(a,e)); w.doc.state=replace(w.doc.state,drawings=(key,)); w.refresh()
    d.choose_tool('lasso'); application.processEvents()
    d.begin(screen_point(d,.08,.25),1)
    for point in ((.2,.25),(.2,.35),(.08,.35),(.08,.25)): d.move(screen_point(d,*point),1)
    d.finish(); assert d.selection.indices==(0,)
    d.begin(screen_point(d,.15,.3),1); d.move(screen_point(d,.15,.5),1); d.finish()
    image=pixels(render_marks(w.doc.state.drawings[0].marks,640,360))
    assert image[180,288,3]==0 and image[180,128,3]>0
    assert len(d.selection.indices)==1
    w.undo(); assert w.doc.state.drawings==(key,)
    w.redo(); assert w.doc.state.drawings[0].marks[-1].tool=='group'


def test_static_gif_with_long_holds_imports(tmp_path,monkeypatch):
    import subprocess
    from media import ffmpeg,prepare_media
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    path=tmp_path/'hold.gif'
    subprocess.run([ffmpeg(),'-v','error','-f','lavfi','-i','color=red:s=64x48:r=1/2:d=4','-loop','0',str(path)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    media=prepare_media(path)
    from fractions import Fraction
    assert 1<=Fraction(media['fps'])<=240 and media['frames']>=4
