# SPDX-License-Identifier: GPL-3.0-only
import time
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog,QPushButton
from PySide6.QtTest import QTest
from test_drawing import application,window
from model import State,Segment
from drawing import DrawingKey,Mark
from preferences import ShortcutDialog,load_preferences
from shortcut_edit import ConflictDialog


def test_marker_toggle_and_preserved_selection(window):
 w=window; w.doc.state=replace(w.doc.state,position=5,selection=(3,12),drawings=(DrawingKey(4,9,(Mark(points=((.2,.2,1),)),)),))
 w.drawing.add_marker(); assert w.doc.state.frame_markers==(5,)
 w.drawing.add_marker(); assert w.doc.state.frame_markers==() and w.doc.state.drawings
 w.doc.undo(); assert w.doc.state.frame_markers==(5,)
 w.drawing.delete_selected_keys(); assert not w.doc.state.drawings and w.doc.state.selection==(3,12)
 w.doc.undo(); assert w.doc.state.drawings and w.doc.state.selection==(3,12)


@pytest.mark.parametrize('accept',[False,True])
def test_conflict_one_dialog_immediate_and_single_response(window,application,monkeypatch,accept):
 w=window;d=ShortcutDialog(w.action_registry,w.preferences,w);d.shortcutsChanged.connect(w.apply_preferences);d.tabs.setCurrentIndex(1);d.show();d.activateWindow()
 key='Dessin/Ajouter un marqueur';other='Outils/Curseur';original=w.preferences['shortcuts'][key];calls=[]
 def respond(box):
  calls.append(1)
  d.key_finished(key)
  QTimer.singleShot(30,lambda:QTest.mouseClick(box.findChildren(QPushButton)[0 if accept else 1],Qt.MouseButton.LeftButton))
  QTimer.singleShot(1500,box.reject)
  return QDialog.exec(box)
 monkeypatch.setattr(ConflictDialog,'exec',respond)
 d.show_key(key);editor=d.editors[key];editor.setFocus();QTest.qWait(40);start=time.monotonic()
 QTest.keySequence(editor,w.action_registry[other][0].shortcut());QTest.qWait(120);application.processEvents()
 assert len(calls)==1 and time.monotonic()-start<.8
 assert load_preferences(w.action_registry)['shortcuts'][key]==(w.preferences['shortcuts'][key] if accept else original)
 if accept: assert not w.action_registry[other][0].shortcut().toString()
 QTest.qWait(1100); assert len(calls)==1
 d.reject()


def test_wipe_pixels_and_drag_with_drawing_tool(window,application):
 from comparison import compose
 w=window;v=w.viewer;w.workspaces.set_timeline_simple(True);w.drawing.choose_tool('brush')
 a=np.zeros((100,200,3),np.uint8);a[:,:,0]=255;b=np.zeros_like(a);b[:,:,2]=255
 output=compose(a,b,'wipe');assert np.all(output[:,:100]==a[:,:100]) and np.all(output[:,100:]==b[:,100:])
 v.comparing=True;v.compare_mode='wipe';v.reference_rgb=b;v.set_frame(a);v.zoom=1.3;v.angle=25;application.processEvents()
 from PySide6.QtGui import QTransform
 from PySide6.QtCore import QPointF
 size=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio)
 transform=QTransform();transform.translate(v.width()/2+v.pan.x(),v.height()/2+v.pan.y());transform.rotate(v.angle);transform.scale(v.zoom,v.zoom)
 start=transform.map(QPointF(0,0)).toPoint();end=transform.map(QPointF(size.width()*.2,0)).toPoint()
 QTest.mousePress(v,Qt.MouseButton.LeftButton,pos=start);QTest.mouseMove(v,end);QTest.mouseRelease(v,Qt.MouseButton.LeftButton,pos=end)
 assert v.wipe_position==pytest.approx(.7,abs=.01) and not w.doc.state.drawings
 assert not v.grab().isNull()
 snapshot=w.comparison_snapshot(); assert snapshot['wipe']==pytest.approx(.7,abs=.01)


def test_association_points_all_launchers_to_current_exe():
 from association import registration_values
 values=registration_values('C:/Cadence nouvelle/Cadence.exe')
 for path in (r'Software\Classes\Applications\Cadence.exe\shell\open\command',r'Software\Classes\Cadence.Video\shell\open\command',r'Software\Classes\CadenceStudio.Project\shell\open\command'):
  assert values[path][0]=='"C:\\Cadence nouvelle\\Cadence.exe" "%1"'
 assert not any('UserChoice' in key for key in values)


def test_ffmpeg_fallback_on_direct_decode_failure(tmp_path,monkeypatch):
 import media,av
 path=tmp_path/'test.mp4';media.run_ffmpeg(['-f','lavfi','-i','color=s=160x90:r=24:d=1','-c:v','libx264',str(path)])
 monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
 def unavailable(*args): raise av.error.InvalidDataError(1,'decoder unavailable')
 monkeypatch.setattr(media,'direct_preview',unavailable)
 m=media.prepare_media(path);assert 'direct_start' not in m and m['frames']==24
 reader=media.PreviewReader()
 try: assert reader.read(m,10).shape==(90,160,3)
 finally: reader.close()

@pytest.mark.parametrize('key,result',[(Qt.Key.Key_R,QDialog.DialogCode.Accepted),(Qt.Key.Key_A,QDialog.DialogCode.Rejected)])
def test_conflict_letter_access(window,application,key,result):
 box=ConflictDialog(window,['Outils/Curseur']);box.show();box.activateWindow();box.raise_();application.setActiveWindow(box);QTest.qWait(80)
 QTest.keyClick(box,key);application.processEvents()
 assert not box.isVisible() and box.result()==result
 box.deleteLater()

@pytest.mark.parametrize('codec,extension,extra',[('libx264','mp4',[]),('libx265','mp4',['-x265-params','log-level=error']),('prores_ks','mov',['-profile:v','0']),('mjpeg','avi',[]),('libvpx-vp9','webm',['-deadline','realtime']),('ffv1','mkv',[])])
def test_bundled_codec_selection(tmp_path,monkeypatch,codec,extension,extra):
 import media
 monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'));source=tmp_path/('source.'+extension)
 media.run_ffmpeg(['-f','lavfi','-i','testsrc2=s=160x96:r=24:d=.5'.replace('d=.5','d=0.5'),'-c:v',codec,*extra,str(source)])
 info=media.prepare_media(source);reader=media.PreviewReader()
 try: assert info['frames']==12 and reader.read(info,5).shape==(96,160,3)
 finally: reader.close()
