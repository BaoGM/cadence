# SPDX-License-Identifier: GPL-3.0-only
import json,time,threading
from pathlib import Path
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPointF,QRectF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton,QLabel
from test_drawing import application,window,screen_point,pixels
from drawing import Mark,DrawingKey,render_marks,active_key
from affine import IDENTITY,rotate,compose,translate,qt
from model import State,Segment,Document,compact
from transform_frame import TransformFrame

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json')); monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache')); monkeypatch.setenv('CADENCE_LANGUAGE','fr')
    yield
    for widget in QApplication.topLevelWidgets():
        if hasattr(widget,'doc') and widget.isVisible(): widget.doc.saved_signature=widget.doc.signature(); widget.close()

def visible(w): return {k for k,p in w.workspaces.panels.items() if not p.isHidden()}
def test_first_open_modes_reset_and_persist(application,tmp_path):
    from app import MainWindow
    w=MainWindow(); w.show(); application.processEvents()
    assert w.workspaces.mode=='read' and visible(w)=={'timeline','transport','timecode'} and w.timeline.simple
    w.workspaces.switch('edit'); application.processEvents()
    assert visible(w)==set(w.workspaces.panels) and not w.timeline.simple
    w.set_layout_editable(True); w.header.hide(); w.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,w.library)
    w.resize(1580,940); application.processEvents(); w.close()
    w=MainWindow(); w.show(); application.processEvents()
    assert w.workspaces.mode=='edit' and w.header.isHidden() and w.layout_editable
    assert w.dockWidgetArea(w.library)==Qt.DockWidgetArea.RightDockWidgetArea
    assert json.loads((tmp_path/'workspaces.json').read_text(encoding='utf-8'))['geometry']
    w.workspaces.switch('read'); w.timecode_overlay.setVisible(False); w.workspaces.switch('edit')
    assert w.header.isHidden() and w.dockWidgetArea(w.library)==Qt.DockWidgetArea.RightDockWidgetArea
    w.reset_panel_layout(); assert visible(w)==set(w.workspaces.panels) and not w.layout_editable
    w.workspaces.switch('read'); assert w.timecode_overlay.isHidden()
    w.reset_panel_layout(); assert visible(w)=={'timeline','transport','timecode'}
    w.workspaces.switch('edit'); w.header.hide()
    from preferences import ShortcutDialog,validate
    dialog=ShortcutDialog(w.action_registry,w.preferences,w)
    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Restaurer l’interface').click()
    assert w.workspaces.mode=='read' and visible(w)=={'timeline','transport','timecode'}
    w.workspaces.switch('edit'); assert visible(w)==set(w.workspaces.panels)
    dialog.reject(); w.close()

def test_options_does_not_wait_for_cache_and_keeps_lazy_keys(window,application,monkeypatch):
    import cache_tools
    from preferences import ShortcutDialog
    entered=threading.Event(); release=threading.Event()
    def slow(): entered.set(); release.wait(2); return 1048576
    monkeypatch.setattr(cache_tools,'cache_bytes',slow)
    start=time.perf_counter(); d=ShortcutDialog(window.action_registry,window.preferences,window); elapsed=time.perf_counter()-start
    from preferences import validate
    assert elapsed<1 and not d.keys_ready and d.collect()['shortcuts']==validate(window.preferences,window.action_registry)['shortcuts']
    d.show(); application.processEvents(); assert entered.wait(1)
    assert not any('Le cache accélère' in l.text() for l in d.findChildren(QLabel))
    d.tabs.setCurrentIndex(1); assert len(d.editors)==len(window.action_registry)
    release.set(); QTest.qWait(40); application.processEvents(); assert '1.0' in d.cache_label.text()
    d.reject()

def test_frame_modifiers_and_corner_rotation():
    r=QRectF(.2,.2,.4,.3); f=TransformFrame(r,16/9)
    f.begin(4,r.bottomRight(),Qt.KeyboardModifier.ControlModifier); f.update(r.bottomRight()+QPointF(.1,.05),Qt.KeyboardModifier.ControlModifier)
    assert f.rect.center()==r.center() and f.rect.width()==pytest.approx(.6)
    before=QRectF(f.rect); f.update(r.bottomRight()+QPointF(.2,.15),Qt.KeyboardModifier.AltModifier)
    assert f.rect.size()==before.size() and f.rect.center()==before.center()+QPointF(.1,.1)
    f=TransformFrame(r,16/9); corner=r.topRight()+QPointF(.015,-.015)
    assert f.hit(corner,1000,562)=='rotate'
    center=r.center(); matrix=qt(rotate(90,center,16/9)); f.begin('rotate',corner,Qt.KeyboardModifier.NoModifier); f.update(matrix.map(corner),Qt.KeyboardModifier.NoModifier)
    assert f.angle==pytest.approx(90) and f.rect==r

def draw_state(w,marks):
    w.workspaces.switch('edit'); w.request_frame=lambda:None
    key=DrawingKey(0,20,tuple(marks)); w.doc.state=replace(w.doc.state,drawings=(key,),position=4)
    w.refresh(); d=w.drawing; d.choose_tool('lasso'); d.selection.indices=tuple(range(len(marks))); d.selection.source=w.doc.state.drawings; d.selection.key_start=0
    return key

def gesture(w,start,end,mods=Qt.KeyboardModifier.NoModifier):
    for kind,p,button in ((QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton),(QEvent.Type.MouseMove,end,Qt.MouseButton.NoButton),(QEvent.Type.MouseButtonRelease,end,Qt.MouseButton.LeftButton)):
        screen=screen_point(w.drawing,p.x(),p.y()); QApplication.sendEvent(w.viewer,QMouseEvent(kind,screen,screen,button,Qt.MouseButton.LeftButton,mods))

def test_ctrl_t_selection_center_move_rotation_history_and_save(window,application,tmp_path):
    w=window; original=draw_state(w,[Mark(points=((.2,.3,1),(.4,.3,1)),pressure=False),Mark(tool='text',points=((.5,.5,1),),text='Texte',box=(.2,.1)),Mark(tool='ellipse',points=((.55,.2,1),(.7,.4,1)))])
    before=w.doc.state; g=w.clip_tools; w.activateWindow(); w.viewer.setFocus(); application.processEvents()
    QTest.keyClick(w.viewer,Qt.Key.Key_T,Qt.KeyboardModifier.ControlModifier); assert g.target=='drawing' and g.mode=='resize'
    r=QRectF(g.rect); center=r.center(); gesture(w,r.bottomRight(),r.bottomRight()+QPointF(.05,.05))
    assert g.rect.center()==center and g.rect.width()>r.width()
    moved=QRectF(g.rect); gesture(w,g.rect.topLeft(),g.rect.topLeft()+QPointF(.08,.03),Qt.KeyboardModifier.AltModifier)
    assert g.rect.center()==moved.center()+QPointF(.08,.03)
    corner=g.rect.topRight()+QPointF(.015,-.015); endpoint=qt(rotate(45,g.rect.center(),g.frame.aspect)).map(corner)
    gesture(w,corner,endpoint); assert g.frame.angle==pytest.approx(45,abs=.01)
    QTest.keyClick(w.viewer,Qt.Key.Key_Return)
    assert w.doc.state.segments==before.segments and all(m.transform!=IDENTITY for m in w.doc.state.drawings[0].marks)
    after=w.doc.state; w.doc.save(tmp_path/'affine.cadence'); assert Document.load(tmp_path/'affine.cadence').state==after
    w.undo(); assert w.doc.state.drawings==before.drawings
    w.redo(); assert w.doc.state.drawings==after.drawings
    w.drawing.selection.indices=(); g.activate('resize'); assert g.target=='clip'
    g.cancel()

def test_affine_eraser_follows_selected_ink(window):
    w=window; brush=Mark(points=((.3,.3,1),),size=.3,color='#ff0000',pressure=False); erase=Mark(tool='eraser',points=((.3,.3,1),),size=.1,pressure=False)
    key=draw_state(w,[brush,erase]); w.drawing.selection.indices=(0,)
    g=w.clip_tools; g.activate('resize'); assert g.target=='drawing'
    g.rect=g.rect.translated(.3,.2); g.update_pending(); g.commit()
    result=pixels(render_marks(w.doc.state.drawings[0].marks,200,100))
    assert result[50,120,3]==0 and result[50,130,3]>0 and result[30,60,3]==0
    assert w.drawing.selection.indices==(1,)

def test_single_selection_ctrl_center_cancel_noop_and_text_move(window):
    w=window; brush=Mark(points=((.3,.3,1),),size=.3,pressure=False); erase=Mark(tool='eraser',points=((.3,.3,1),),size=.1,pressure=False)
    draw_state(w,[brush,erase]); d=w.drawing; d.selection.indices=(0,); g=w.clip_tools; before=w.doc.state; count=len(w.doc.undo_stack)
    g.activate('resize'); g.commit()
    assert w.doc.state==before and d.selection.indices==(0,) and len(w.doc.undo_stack)==count
    g.activate('resize'); r=QRectF(g.rect)
    gesture(w,r.bottomRight(),r.bottomRight()+QPointF(.03,.03),Qt.KeyboardModifier.ControlModifier)
    assert g.rect.center()==r.center() and g.rect.width()>r.width()
    g.cancel(); assert w.doc.state==before and d.selection.preview is None
    draw_state(w,[Mark(tool='text',points=((.3,.3,1),),text='Cadence',box=(.3,.1))])
    g.activate('resize'); g.frame.angle=30; g.update_pending(); g.commit()
    key=w.doc.state.drawings[0]; center=d.selection.bounds(key).center()
    d.selection.begin((center.x(),center.y()),'text',True); d.selection.move((center.x()+.08,center.y()+.05)); d.selection.finish()
    result=w.doc.state.drawings[0].marks[0]
    assert result.transform==pytest.approx(compose(translate(.08,.05),key.marks[0].transform))

def test_close_from_fullscreen_preserves_mode_panels(application,tmp_path):
    from app import MainWindow
    w=MainWindow(); w.show(); application.processEvents(); w.workspaces.switch('edit'); w.header.hide(); w.toggle_fullscreen(); application.processEvents(); w.close()
    w=MainWindow(); w.show(); application.processEvents()
    assert w.workspaces.mode=='edit' and w.header.isHidden() and not w.timeline_panel.isHidden() and not w.video_fullscreen
    w.close()

def test_clip_rotate_preview_and_export(application,tmp_path):
    import av,subprocess
    from clip_geometry import apply_geometry,geometry_filter
    from media import ffmpeg
    image=np.zeros((100,200,3),np.uint8); image[20:35,60:90,0]=255
    seg=Segment('a',0,1,placement=(.1,.15,.6,.6),rotation=90)
    preview=apply_geometry(image,seg,2)
    raw=tmp_path/'rgb.raw'; raw.write_bytes(image.tobytes()); output=tmp_path/'rotated.mp4'
    result=subprocess.run([ffmpeg(),'-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','200x100','-i',str(raw),'-vf',geometry_filter(seg,200,100),'-frames:v','1','-c:v','libx264','-crf','0',str(output)],capture_output=True)
    assert result.returncode==0,result.stderr
    with av.open(str(output)) as c: rendered=next(c.decode(video=0)).to_ndarray(format='rgb24')
    a=np.argwhere(preview[:,:,0]>180).mean(axis=0); b=np.argwhere(rendered[:,:,0]>180).mean(axis=0)
    assert np.linalg.norm(a-b)<2
    assert len(compact((Segment('a',0,1),replace(seg,start=1,end=2))))==2

def test_timeline_exception_and_disable_translation(window,monkeypatch):
    import ui_text
    assert ui_text.tr('Afficher la timeline')=='Afficher la timeline'
    assert ui_text.tr('Toute la timeline')=='Toute la timeline'
    monkeypatch.setattr(ui_text,'_language','en')
    menu=window.timeline.context_menu(QPointF(window.timeline.x_for(3),60))
    assert 'Disable / Enable video' in [a.text() for a in menu.actions()]
    menu.deleteLater()
