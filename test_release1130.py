# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from types import SimpleNamespace
import threading

from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
import pytest

from test_sync1120 import application, link
from capture import CaptureDialog
from capture_inputs import CaptureInputs, key_caption


def test_restart_notice_once(link, monkeypatch):
    link.stop()
    messages=[]
    monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args))
    link.prepare_connector=lambda:True
    link.set_enabled(True)
    assert len(messages)==1 and 'Blender' in messages[0][2]
    link.stop(); link.prepare_connector=lambda:False; link.set_enabled(True)
    assert len(messages)==1


def test_explicit_rate_after_refusal_and_all_media_undo(link, monkeypatch):
    from pathlib import Path
    from media import prepare_media
    from model import Document
    w=link.window
    media=prepare_media(Path(__file__).parent/'assets/Demonstration.mp4',quality='480p')
    other=dict(media,id=media['id']+'-second')
    w.doc=Document(); w.doc.append_media([media,other]); baseline=w.doc.state
    w.preferences={'preview_quality':'480p'}
    w.pause=w.commit_exposure=w.refresh=w.request_frame=lambda:None
    w.drawing=SimpleNamespace(finish=lambda:None)
    w.begin_task=lambda title,prepare,apply:apply(prepare(lambda *args:None,threading.Event()))
    link.metadata=dict(fps=Fraction(30),frame=0,start=0,end=400)
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.No)
    link.offer_rate(w.doc,media['id'],Fraction(24),Fraction(30))
    assert w.doc.state==baseline
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
    link.adapt_current(True)
    assert all(w.doc.media[s.media]['cadence']['rate']=='30' for s in w.doc.state.segments)
    assert w.doc.state.length==baseline.length and w.doc.fps==24
    w.doc.undo(); assert w.doc.state==baseline
    link.adapt_current(False)
    assert w.doc.media[w.doc.state.segments[0].media]['cadence']['rate']=='30'
    assert w.doc.state.segments[-1].media==other['id']


def test_capture_preferences_cancel_and_keep_window(application,tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json'))
    parent=QWidget(); parent.show()
    dialog=CaptureDialog(parent)
    try:
        assert not any(c.isChecked() for c in (dialog.include_cadence,dialog.include_keyboard,dialog.include_clicks))
        assert dialog.include_cursor.isChecked()
        for c in (dialog.include_cadence,dialog.include_keyboard,dialog.include_clicks): c.setChecked(True)
        dialog.save_settings()
        def arm(): dialog.armed=True
        monkeypatch.setattr(dialog,'begin',arm)
        dialog.quick_begin(); assert not parent.isMinimized()
        dialog.include_cadence.setChecked(False); dialog.quick_begin(); assert parent.isMinimized()
        parent.showNormal()
        screen=SimpleNamespace(geometry=lambda:QRect(0,0,640,360))
        dialog.inputs.reader=SimpleNamespace(pressed=lambda keyboard:set(),name=lambda key:str(key))
        dialog.inputs.start(screen,None,True,True)
        assert dialog.inputs.timer.isActive()
        dialog.reject(); assert not dialog.inputs.timer.isActive() and dialog.inputs.isHidden()
        restored=CaptureDialog(parent)
        assert all(c.isChecked() for c in (restored.include_cadence,restored.include_keyboard,restored.include_clicks))
        restored.reject(); restored.deleteLater()
    finally:
        dialog.reject(); dialog.deleteLater(); parent.close(); parent.deleteLater()


def test_input_overlay_held_buttons_keys_and_stop(application,monkeypatch):
    pressed=set()
    reader=SimpleNamespace(pressed=lambda keyboard:set(pressed),name=lambda key:{17:'Ctrl',65:'A',16:'Maj'}.get(key,''))
    overlay=CaptureInputs(reader)
    screen=SimpleNamespace(geometry=lambda:QRect(-1280,100,1280,720))
    monkeypatch.setattr(QCursor,'pos',lambda:QPoint(-1200,180))
    try:
        overlay.start(screen,QRect(10,20,400,300),True,True)
        assert overlay.geometry()==QRect(-1270,120,400,300)
        assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
        pressed.update((17,162,65,1)); overlay.tick()
        assert overlay.caption=='Ctrl + A' and overlay.buttons=={1}
        assert overlay.pointer==QPoint(70,60)
        for button in (2,4):
            pressed.clear(); pressed.add(button); overlay.tick(); assert overlay.buttons=={button}
        pressed.clear(); overlay.tick(); assert not overlay.buttons
        overlay.expires=0; overlay.tick(); assert not overlay.caption
        overlay.stop(); assert not overlay.timer.isActive() and not overlay.previous and overlay.isHidden()
        overlay.start(screen,None,False,False); assert not overlay.timer.isActive()
        assert key_caption({16,160,17,162,65},reader.name)=='Ctrl + Maj + A'
    finally: overlay.stop(); overlay.deleteLater()


def test_quarter_screen_and_compact_transport(application,tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json'))
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    monkeypatch.setenv('CADENCE_RENDERER','software')
    from app import MainWindow
    w=MainWindow(); w.show(); application.processEvents()
    try:
        w.media_info.setText('3840 × 2160 · 29.970 images/s')
        for mode in ('read','edit'):
            w.workspaces.switch(mode)
            for width,height in ((960,500),(800,450),(640,400)):
                w.resize(width,height); application.processEvents(); QTest.qWait(20)
                assert w.size().width()<=width and w.size().height()<=height
                assert w.viewer.width()>=150 and w.viewer.height()>=70
                assert w.transport_widget.width()==w.width()
                assert w.timeline_panel.width()==w.width()
                assert w.timeline_panel.geometry().bottom()<w.height()
        w.resize(1360,890); application.processEvents(); QTest.qWait(20)
        assert not w.compact_transport.compact and w.transport_widget.widget().height()==42
        assert not any('Aligner les positions' in key for key in w.action_registry)
        assert w.action_registry['Synchronisation 3D/Adapter la cadence du média courant…'][1]=='Ctrl+Alt+R'
    finally:
        w.doc.saved_signature=w.doc.signature(); w.close(); application.processEvents()
