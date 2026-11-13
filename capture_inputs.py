# SPDX-License-Identifier: GPL-3.0-only
import ctypes
import os
from ctypes import wintypes
import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QCursor
from PySide6.QtWidgets import QWidget

from ui_text import tr


class WindowsInputs:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        self.user.GetKeyboardLayout.restype = wintypes.HANDLE
        self.user.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HANDLE]
        self.user.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte), wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, wintypes.HANDLE]

    def pressed(self, keyboard):
        keys = range(8, 255) if keyboard else ()
        return {key for key in (1, 2, 4, *keys) if self.user.GetAsyncKeyState(key) & 0x8000}

    def name(self, key):
        fixed = {8:'Retour arrière', 9:'Tab', 13:'Entrée', 16:'Maj', 17:'Ctrl', 18:'Alt',
            19:'Pause', 20:'Verr. maj', 27:'Échap', 32:'Espace', 33:'Page préc.', 34:'Page suiv.',
            35:'Fin', 36:'Début', 37:'←', 38:'↑', 39:'→', 40:'↓', 45:'Inser', 46:'Suppr',
            91:'Windows', 92:'Windows', 144:'Verr. num', 145:'Arrêt défil.'}
        if key in fixed: return tr(fixed[key])
        if 112 <= key <= 135: return f'F{key - 111}'
        if 96 <= key <= 105: return str(key - 96)
        thread = self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), None)
        layout = self.user.GetKeyboardLayout(thread)
        scan = self.user.MapVirtualKeyExW(key, 0, layout)
        state = (ctypes.c_ubyte * 256)()
        text = ctypes.create_unicode_buffer(8)
        # Flag 4 leaves the foreground application's dead-key state untouched.
        count = self.user.ToUnicodeEx(key, scan, state, text, len(text), 4, layout)
        return text.value.upper() if count and text.value.isprintable() else ''


def key_caption(keys, name):
    parts = []
    for key, aliases in ((17,(17,162,163)), (18,(18,164,165)), (16,(16,160,161)), (91,(91,92))):
        if any(k in keys for k in aliases): parts.append(name(key))
    excluded = {1,2,4,16,17,18,91,92,160,161,162,163,164,165}
    parts.extend(filter(None, (name(key) for key in sorted(keys - excluded))))
    return ' + '.join(parts[:6])


class CaptureInputs(QWidget):
    def __init__(self, reader=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.reader = reader
        self.keyboard = self.clicks = False
        self.previous = set()
        self.caption = ''
        self.expires = 0.
        self.buttons = set()
        self.pointer = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    def start(self, screen, region, keyboard, clicks):
        self.stop()
        self.keyboard, self.clicks = keyboard, clicks
        if not keyboard and not clicks: return
        if self.reader is None:
            if os.name=='nt': self.reader = WindowsInputs()
            else:
                from capture_x11 import Inputs
                self.reader = Inputs()
        area = screen.geometry() if region is None else region.translated(screen.geometry().topLeft())
        self.setGeometry(area)
        self.previous = self.reader.pressed(keyboard)
        self.show()
        self.timer.start()

    def tick(self):
        keys = self.reader.pressed(self.keyboard)
        now = time.monotonic()
        old = (self.caption, self.buttons, self.pointer)
        if self.keyboard and keys - self.previous - {1,2,4}:
            self.caption = key_caption(keys, self.reader.name)
            self.expires = now + 1.2
        elif now >= self.expires:
            self.caption = ''
        self.buttons = keys & {1,2,4} if self.clicks else set()
        self.pointer = self.mapFromGlobal(QCursor.pos()) if self.buttons else None
        self.previous = keys
        if old != (self.caption, self.buttons, self.pointer): self.update()

    def stop(self):
        self.timer.stop()
        if os.name!='nt' and self.reader is not None and hasattr(self.reader,'close'):
            self.reader.close(); self.reader=None
        self.hide()
        self.previous.clear()
        self.caption = ''
        self.buttons.clear()
        self.pointer = None
        self.expires = 0.

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.pointer is not None and self.rect().contains(self.pointer):
            painter.setBrush(QColor(255, 218, 75, 65))
            painter.drawEllipse(self.pointer, 18, 18)
            painter.setBrush(QColor(255, 218, 75, 50))
            painter.drawEllipse(self.pointer, 11, 11)
        if self.caption:
            font = QFont('Segoe UI', 10)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            width = min(self.width() - 16, metrics.horizontalAdvance(self.caption) + 24)
            height = metrics.height() + 12
            area = QRectF((self.width() - width) / 2, max(0,self.height() - height - 16), width, height)
            painter.setBrush(QColor(0, 0, 0, 205))
            painter.drawRoundedRect(area, 5, 5)
            painter.setPen(QColor('#f2f3f5'))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, metrics.elidedText(self.caption, Qt.TextElideMode.ElideRight, max(1,int(width)-16)))
