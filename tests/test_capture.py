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
