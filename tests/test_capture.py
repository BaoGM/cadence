# SPDX-License-Identifier: GPL-3.0-only
import sys,os,time,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from PySide6.QtCore import QRect,Qt
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox
from PySide6.QtGui import QIcon
from capture import physical_region,capture_args,CaptureDialog,StopHotkey
class Screen:
    def name(self): return 'left'
    def geometry(self): return QRect(-1280,0,1280,720)
def test_dpi_region_and_negative_origin():
    assert physical_region(Screen(),QRect(10,20,101,51),{'left':(-1920,0,1920,1080)})==(-1905,30,151,76)
    with pytest.raises(RuntimeError): physical_region(Screen(),QRect(0,0,20,20),{})
def test_encoding_preserves_odd_region_and_existing_file():
    args=capture_args((-100,20,151,77),30,False,'space name.mp4')
    assert '-n' in args and args[args.index('-draw_mouse')+1]=='0'
    assert args[args.index('-video_size')+1]=='151x77'
    assert 'pad=ceil(iw/2)*2:ceil(ih/2)*2' in args and args[-1]=='space name.mp4'
def test_cancel_countdown_releases_hotkey(monkeypatch):
    app=QApplication.instance() or QApplication([])
    parent=QDialog(); d=CaptureDialog(parent); d.countdown=3; d.timer.start()
    d.reject(); assert not d.timer.isActive() and d.countdown==0
    d.deleteLater(); parent.deleteLater(); app.processEvents()
def test_completed_capture_accepted(monkeypatch,tmp_path):
    app=QApplication.instance() or QApplication([])
    parent=QDialog(); d=CaptureDialog(parent)
    import tempfile,io
    class Process: stdin=io.BytesIO()
    d.proc=Process(); d.log=tempfile.TemporaryFile(); d.path=tmp_path/'video.mp4'; d.path.write_bytes(b'captured')
    d.recording_finished(0)
    assert d.output==str(d.path) and d.result()==QDialog.DialogCode.Accepted and d.proc is None
    d.deleteLater(); parent.deleteLater(); app.processEvents()
def test_capture_cancel_does_not_import(monkeypatch):
    app=QApplication.instance() or QApplication([])
    from app import MainWindow
    monkeypatch.setenv('CADENCE_PREFS',str(Path('work')/'capture-test-prefs.json'))
    w=MainWindow(); imported=[]; w.append_paths=lambda paths:imported.extend(paths)
    monkeypatch.setattr(CaptureDialog,'run',lambda self,**kw:QDialog.DialogCode.Rejected)
    w.capture_screen(); assert imported==[]
    def accepted(self,**kw): self.output='capture.mp4'; return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CaptureDialog,'run',accepted)
    w.capture_screen(); assert imported==['capture.mp4']
    w.doc.saved_signature=w.doc.signature(); w.close()

def test_options_closed_without_recording_used_by_quick_capture(monkeypatch,tmp_path):
    import json
    app=QApplication.instance() or QApplication([])
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json'))
    parent=QDialog()
    dialog=CaptureDialog(parent)
    dialog.include_cadence.setChecked(True)
    dialog.include_keyboard.setChecked(True)
    dialog.include_cursor.setChecked(False)
    dialog.include_clicks.setChecked(True)
    dialog.region=QRect(20,30,100,50)
    dialog.reject()
    data=json.loads((tmp_path/'capture.json').read_text())
    assert not dialog.armed and data['keyboard'] and not data['cursor']
    restored=CaptureDialog(parent)
    assert restored.region==dialog.region
    assert all(c.isChecked() for c in (restored.include_cadence,restored.include_keyboard,restored.include_clicks))
    assert not restored.include_cursor.isChecked()
    restored.reject(); restored.deleteLater(); dialog.deleteLater(); parent.deleteLater()
    app.processEvents()

def test_stopping_keeps_mirror_and_window_out_until_last_frame(monkeypatch,tmp_path):
    import io,tempfile
    from types import SimpleNamespace
    app=QApplication.instance() or QApplication([])
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json'))
    parent=QDialog(); parent.show(); parent.video_mirror=QDialog(); parent.video_mirror.show()
    dialog=CaptureDialog(parent)
    try:
        dialog.conceal_window()
        assert parent.isMinimized() and parent.video_mirror.isHidden()
        dialog.proc=SimpleNamespace(stdin=io.BytesIO())
        dialog.log=tempfile.TemporaryFile(); dialog.path=tmp_path/'video.mp4'
        dialog.path.write_bytes(b'completed')
        dialog.armed=True
        dialog.stop()
        assert dialog.stopping and dialog.proc.stdin.getvalue()==b'q\n'
        assert parent.isMinimized() and parent.video_mirror.isHidden()
        dialog.recording_finished(0)
        assert not parent.isMinimized() and parent.video_mirror.isVisible()
        assert dialog.output==str(dialog.path)
    finally:
        parent.video_mirror.close(); parent.close(); dialog.deleteLater(); parent.deleteLater(); app.processEvents()

def test_old_monitor_settings_survive_dpi_change_and_missing_display(monkeypatch,tmp_path):
    import json
    app=QApplication.instance() or QApplication([])
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json'))
    screen=app.primaryScreen(); g=screen.geometry(); parent=QDialog()
    settings=tmp_path/'capture.json'
    for label,region,review in (
        (f'{screen.name()} · {2*g.width()} × {2*g.height()}',QRect(8,9,15,18),False),
        ('missing-monitor · 1920 × 1080',None,True),
    ):
        settings.write_text(json.dumps(dict(screen=label,region=[16,18,30,36])),encoding='utf-8')
        d=CaptureDialog(parent)
        assert d.region==region and d.review_target is review
        assert d.screens.currentData()==screen
        d.reject(); d.deleteLater()
    parent.deleteLater(); app.processEvents()
