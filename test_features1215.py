# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
import ctypes,time,threading
import pytest
from PySide6.QtCore import Qt,QEvent,QObject,QPoint
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMessageBox,QDialogButtonBox
from PySide6.QtTest import QTest
from test_drawing import application,window
from model import Document,State,Segment
from drawing import DrawingKey,Mark
from preferences import ShortcutDialog,load_preferences,defaults
from media import PreviewReader,prefetch_frames,DecodeSuperseded


def test_markers_independent_undo_save_and_menu(window,tmp_path):
 w=window; w.doc.state=State((Segment(None,0,100),),position=12,selection=(10,20),drawings=(DrawingKey(10,20,(Mark(points=((.2,.2,1.),)),)),))
 original=w.doc.state.drawings; w.refresh(); w.drawing.add_marker()
 assert w.doc.state.frame_markers==(12,) and w.doc.state.drawings==original
 w.doc.undo(); assert not w.doc.state.frame_markers; w.doc.redo()
 path=tmp_path/'markers.cadence'; w.doc.save(path); loaded=Document.load(path)
 assert loaded.state.frame_markers==(12,) and loaded.state.drawings==original
 assert loaded.to_data()['version']==12
 w.refresh()
 menu=w.timeline.context_menu(QPoint(round(w.timeline.x_for(12)),20))
 assert any(a.text()=='Supprimer les marqueurs' and a.isEnabled() for a in menu.actions())
 w.drawing.delete_markers(); assert not w.doc.state.frame_markers and w.doc.state.drawings==original
 w.doc.undo(); w.doc.state=replace(w.doc.state,position=13); w.drawing.navigate(1); assert w.doc.state.position==10
 menu.deleteLater()


def test_adaptive_ticks(window):
 t=window.timeline;window.doc.state=State((Segment(None,0,1000),),frame_markers=(2,30,900));window.refresh()
 for width in (350,800,1600):
  t.resize(width,160)
  for visible in (10,30,300,1000):
   t.zoom=1000/visible; t.view_start=.3
   minor,major=t.ruler_steps(); assert type(minor) is int and minor>=1 and major%minor==0
   assert minor*t.track_width()/t.span()>=9.99
   assert major*t.track_width()/t.span()>=89.99
   for simple in (False,True):
    t.simple=simple; assert not t.grab().isNull()


def test_immediate_shortcut_clear_conflict_cancel_and_replace(window,monkeypatch):
 w=window; d=ShortcutDialog(w.action_registry,w.preferences,w); d.shortcutsChanged.connect(w.apply_preferences)
 first='Lecture/Lecture / pause'; second='Dessin/Ajouter un marqueur'
 d.set_key(first,'Ctrl+Alt+J'); assert w.action_registry[first][0].shortcut().toString()=='Ctrl+Alt+J'
 assert load_preferences(w.action_registry)['shortcuts'][first]=='Ctrl+Alt+J'
 original=w.preferences['shortcuts'][second]
 from shortcut_edit import ConflictDialog
 monkeypatch.setattr(ConflictDialog,'exec',lambda box:0)
 d.set_key(second,'Ctrl+Alt+J'); assert d.editors[second].keySequence().toString()==original
 def choose_replace(box):
  return 1
 monkeypatch.setattr(ConflictDialog,'exec',choose_replace)
 d.set_key(second,'Ctrl+Alt+J'); assert not w.action_registry[first][0].shortcut().toString()
 d.set_key(second,''); assert not load_preferences(w.action_registry)['shortcuts'][second]
 d.scrub.setValue(12); assert w.viewer.scrub_pixels==12
 d.gestures['zoom'][0].setCurrentIndex(2)
 assert w.preferences['canvas']['zoom']['modifiers']=='Shift' and w.preferences['canvas']['rotate']['modifiers']=='Ctrl'
 d.reject(); assert load_preferences(w.action_registry)['shortcuts'][second]==''


@pytest.mark.parametrize('layout',['00000409','0000040C'])
def test_all_shortcuts_under_windows_layout(window,application,layout):
 user=ctypes.windll.user32
 user.GetKeyboardLayout.restype=ctypes.c_void_p;user.LoadKeyboardLayoutW.restype=ctypes.c_void_p;user.LoadKeyboardLayoutW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint]
 user.ActivateKeyboardLayout.argtypes=[ctypes.c_void_p,ctypes.c_uint];user.ActivateKeyboardLayout.restype=ctypes.c_void_p
 previous=user.GetKeyboardLayout(0); selected=user.LoadKeyboardLayoutW(layout,0)
 if not selected: pytest.skip('Keyboard layout unavailable')
 class Guard(QObject):
  def eventFilter(self,obj,event):
   if event.type()==QEvent.Type.Shortcut: self.events.append((obj,event.isAmbiguous()));return True
   return False
 guard=Guard();guard.events=[];w=window
 try:
  assert user.ActivateKeyboardLayout(selected,0)
  w.activateWindow();w.raise_();w.viewer.setFocus();QTest.qWait(40)
  for action,key in w.action_registry.values(): action.setEnabled(True);action.setShortcut(QKeySequence(key));action.installEventFilter(guard)
  for name,(action,key) in w.action_registry.items():
   if key:
    guard.events.clear();QTest.keySequence(w,QKeySequence(key));application.processEvents()
    assert guard.events==[(action,False)],(layout,name,key,guard.events)
 finally:
  for action,_ in w.action_registry.values(): action.removeEventFilter(guard)
  user.ActivateKeyboardLayout(previous,0)


def test_prefetch_budget_both_directions_and_cancellation():
 media=dict(proxy=str(Path(__file__).parent/'assets/Demonstration.mp4'),fps='24',frames=192,width=960,height=540)
 targets=prefetch_frames(media,80,0,192,64*1024*1024)
 assert any(i<80 for _,i in targets) and any(i>80 for _,i in targets)
 assert len(targets)<=96
 reader=PreviewReader(budget=64*1024*1024)
 try:
  with pytest.raises(DecodeSuperseded): reader.read(media,70,lambda:True)
  frame=reader.read(media,70); assert frame.shape==(540,960,3)
  assert reader.cache.frames
  previous=reader.read(media,69); assert previous.shape==frame.shape
 finally: reader.close()

def test_typing_shortcut_is_live_without_save(window,application):
 w=window;d=ShortcutDialog(w.action_registry,w.preferences,w);d.shortcutsChanged.connect(w.apply_preferences);d.tabs.setCurrentIndex(1);d.show();d.activateWindow()
 key='Dessin/Ajouter un marqueur';d.show_key(key);editor=d.editors[key];editor.setFocus();QTest.qWait(40)
 QTest.keySequence(editor,QKeySequence('Ctrl+Alt+J'));QTest.qWait(1200);application.processEvents()
 assert w.action_registry[key][0].shortcut().toString()=='Ctrl+Alt+J'
 assert load_preferences(w.action_registry)['shortcuts'][key]=='Ctrl+Alt+J'
 buttons=d.findChild(QDialogButtonBox)
 assert buttons.button(QDialogButtonBox.StandardButton.Save).isHidden()
 assert buttons.button(QDialogButtonBox.StandardButton.Close).isVisible()
 d.reject()
