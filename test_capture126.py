# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace
from PySide6.QtCore import QRect,Qt
from capture_feedback import RegionOutline
from test_drawing import application

def test_full_monitor_outline_and_recording_fallback(application,monkeypatch):
    outline=RegionOutline(); monkeypatch.setattr(outline,'exclude_from_capture',lambda:True)
    try:
        for area in (QRect(0,0,1920,1080),QRect(-1280,120,1280,720)):
            screen=SimpleNamespace(geometry=lambda:area)
            outline.display(screen,None)
            assert outline.geometry()==area and outline.isVisible() and outline.full_screen
            assert outline.windowFlags()&Qt.WindowType.WindowTransparentForInput
            outline.prepare_recording(); assert outline.isVisible()
        outline.display(screen,QRect(20,30,200,100))
        assert outline.geometry()==QRect(-1263,147,206,106) and not outline.full_screen
        monkeypatch.setattr(outline,'exclude_from_capture',lambda:False)
        outline.display(screen,None); assert outline.isVisible()
        outline.prepare_recording(); assert outline.isHidden()
    finally: outline.close(); outline.deleteLater()
