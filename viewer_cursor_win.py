# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter,Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class NativeCursorBoundary(QAbstractNativeEventFilter):
    def __init__(self,guard):
        super().__init__(); self.guard=guard
        self.user32=ctypes.WinDLL('user32',use_last_error=True)
        self.user32.LoadCursorW.argtypes=[wintypes.HINSTANCE,ctypes.c_void_p]
        self.user32.LoadCursorW.restype=wintypes.HANDLE
        self.user32.SetCursor.argtypes=[wintypes.HANDLE]
        self.user32.SetCursor.restype=wintypes.HANDLE
        self.arrow=self.user32.LoadCursorW(None,32512)
        if not self.arrow: raise ctypes.WinError(ctypes.get_last_error())

    def nativeEventFilter(self,event_type,message):
        if event_type!=b'windows_generic_MSG': return False,0
        msg=wintypes.MSG.from_address(int(message))
        if msg.message!=0x0020 or (msg.lParam&0xffff)!=1 or QApplication.overrideCursor() is not None:
            return False,0
        hit=QApplication.widgetAt(QCursor.pos())
        if hit is None or hit.cursor().shape()!=Qt.CursorShape.ArrowCursor: return False,0
        viewer=self.guard.viewer
        if (hit is viewer or viewer.isAncestorOf(hit)) and hit.window() is viewer.window(): return False,0
        owner=hit
        while owner is not None and owner is not viewer.window(): owner=owner.parentWidget()
        if owner is None: return False,0
        # Native video children can leave Windows displaying their last cursor despite Qt's arrow state.
        self.guard.boundary(True)
        self.user32.SetCursor(self.arrow)
        return True,1
