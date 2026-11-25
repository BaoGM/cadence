# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication


WM_WINDOWPOSCHANGING = 0x0046
SWP_NOSIZE = 1
DWMWA_TRANSITIONS_FORCEDISABLED = 3


class WindowPlacement(ctypes.Structure):
    _fields_ = [('length', wintypes.UINT), ('flags', wintypes.UINT), ('show', wintypes.UINT),
                ('minimum', wintypes.POINT), ('maximum', wintypes.POINT), ('normal', wintypes.RECT)]


class WindowPosition(ctypes.Structure):
    _fields_ = [('window', wintypes.HWND), ('after', wintypes.HWND), ('x', ctypes.c_int),
                ('y', ctypes.c_int), ('width', ctypes.c_int), ('height', ctypes.c_int), ('flags', wintypes.UINT)]


class MaximizedReturn(QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.hwnd = int(window.winId())
        self.frame = wintypes.RECT()
        self.placement = WindowPlacement(length=ctypes.sizeof(WindowPlacement))
        self.user = ctypes.windll.user32
        hwnd = wintypes.HWND(self.hwnd)
        self.ready = (self.user.GetWindowRect(hwnd, ctypes.byref(self.frame)) and
                      self.user.GetWindowPlacement(hwnd, ctypes.byref(self.placement)))

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.hWnd == self.hwnd and msg.message == WM_WINDOWPOSCHANGING:
            pos = WindowPosition.from_address(msg.lParam)
            if not pos.flags & SWP_NOSIZE:
                # Qt briefly restores the smaller normal frame before maximizing.
                pos.x, pos.y = self.frame.left, self.frame.top
                pos.width, pos.height = self.frame.right-pos.x, self.frame.bottom-pos.y
        return False, 0

    def restore(self, window):
        if not self.ready:
            window.showMaximized()
            return
        app = QApplication.instance()
        hwnd = wintypes.HWND(self.hwnd)
        dwm = ctypes.windll.dwmapi
        disabled = wintypes.BOOL(True)
        previous = wintypes.BOOL(False)
        dwm.DwmGetWindowAttribute(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(previous), ctypes.sizeof(previous))
        changed = dwm.DwmSetWindowAttribute(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(disabled), ctypes.sizeof(disabled)) == 0
        app.installNativeEventFilter(self)
        try:
            window.showMaximized()
        finally:
            app.removeNativeEventFilter(self)
            self.user.SetWindowPlacement(hwnd, ctypes.byref(self.placement))
            if changed:
                dwm.DwmSetWindowAttribute(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(previous), ctypes.sizeof(previous))
