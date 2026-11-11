# SPDX-License-Identifier: GPL-3.0-only
"""Non-activating capture countdown and start cue."""
from ui_text import tr
import ctypes,os
from ctypes import wintypes
from PySide6.QtCore import Qt,QTimer,QRectF
from PySide6.QtGui import QPainter,QColor,QFont,QPixmap,QIcon
from PySide6.QtWidgets import QApplication,QWidget

def start_sound():
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK)
    except (ImportError,RuntimeError): QApplication.beep()

def recording_icon():
    pixmap=QPixmap(32,32); pixmap.fill(Qt.GlobalColor.transparent)
    p=QPainter(pixmap); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#ff635c')); p.drawEllipse(QRectF(3,3,26,26)); p.end()
    return QIcon(pixmap)

class CaptureFeedback(QWidget):
    def __init__(self):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); self.setFixedSize(350,76)
        self.title=''; self.subtitle=''; self.excluded=False
        self.hide_timer=QTimer(self); self.hide_timer.setSingleShot(True); self.hide_timer.timeout.connect(self.hide)
    def exclude_from_capture(self):
        if os.name!='nt': return False
        fn=ctypes.windll.user32.SetWindowDisplayAffinity
        fn.argtypes=[wintypes.HWND,wintypes.DWORD]; fn.restype=wintypes.BOOL
        return bool(fn(int(self.winId()),0x11))
    def present(self,screen,title,subtitle,timeout=0):
        self.hide_timer.stop(); self.title=title; self.subtitle=subtitle
        area=screen.availableGeometry(); self.move(area.center().x()-self.width()//2,area.top()+24)
        self.excluded=self.exclude_from_capture()
        self.show(); self.raise_(); self.update()
        if timeout: self.hide_timer.start(timeout)
    def countdown(self,screen,seconds):
        text=f'Capture dans {seconds}…'
        if self.title!=text: self.present(screen,text,'Ctrl + Maj + F8 pour annuler')
    def recording(self,screen):
        # Keep the cue out of recorded pixels; the red tray icon is the fallback.
        if self.exclude_from_capture(): self.present(screen,'●  Capture en cours','Ctrl + Maj + F8 pour arrêter',1800)
        else: self.hide()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor('#536579')); p.setBrush(QColor('#17212c')); p.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),12,12)
        p.setPen(QColor('#ff8174')); p.setFont(QFont('Segoe UI',13,QFont.Weight.DemiBold)); p.drawText(QRectF(12,9,self.width()-24,29),Qt.AlignmentFlag.AlignCenter,tr(self.title))
        p.setPen(QColor('#dce4ee')); p.setFont(QFont('Segoe UI',10)); p.drawText(QRectF(12,39,self.width()-24,23),Qt.AlignmentFlag.AlignCenter,tr(self.subtitle)); p.end()

class RegionOutline(CaptureFeedback):
    def __init__(self):
        super().__init__(); self.setMinimumSize(0,0); self.setMaximumSize(16777215,16777215); self.full_screen=False
    def display(self,screen,region):
        if screen is None: self.hide(); return
        self.full_screen=region is None
        area=screen.geometry() if self.full_screen else region.translated(screen.geometry().topLeft()).adjusted(-3,-3,3,3)
        self.setGeometry(area); self.excluded=self.exclude_from_capture(); self.show(); self.raise_(); self.update()
    def prepare_recording(self):
        if self.full_screen and not self.excluded: self.hide()
    def paintEvent(self,event):
        from PySide6.QtGui import QPen
        p=QPainter(self); p.setPen(QPen(QColor('#68e0cf'),2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(self.rect()).adjusted(1,1,-1,-1)); p.end()
