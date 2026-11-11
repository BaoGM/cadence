# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication,QWidget


class ViewerCursor(QObject):
    def __init__(self,viewer):
        super().__init__(viewer); self.viewer=viewer; self.outside=False; self.desired=QCursor(Qt.CursorShape.OpenHandCursor); self.active=False; self.native=None

    def activate(self):
        if self.native is None and QApplication.platformName()=='windows':
            from viewer_cursor_win import NativeCursorBoundary
            self.native=NativeCursorBoundary(self)
            app=QApplication.instance(); app.installNativeEventFilter(self.native)
            native=self.native
            self.viewer.destroyed.connect(lambda:app.removeNativeEventFilter(native))
        if not self.active:
            self.active=True; QApplication.instance().installEventFilter(self)

    def deactivate(self):
        if self.active:
            self.active=False; QApplication.instance().removeEventFilter(self)
        self.boundary(True); self.release()

    def set_cursor(self,cursor):
        self.desired=QCursor(cursor)
        QWidget.setCursor(self.viewer,Qt.CursorShape.ArrowCursor if self.outside else self.desired)

    def boundary(self,outside):
        if self.outside==outside: return
        self.outside=outside
        QWidget.setCursor(self.viewer,Qt.CursorShape.ArrowCursor if outside else self.desired)

    def release(self):
        v=self.viewer; v.finish_navigation(restore=False)
        drawing=getattr(v,'draw_controller',None)
        if drawing: drawing.temporary_picker=False
        if drawing and (drawing.sampling or drawing.size_drag or drawing.stroke or drawing.text_drag or drawing.tablet_down or drawing.selection.gesture):
            drawing.sampling=False; drawing.finish_size_drag(restore=False); drawing.finish()
        overlay=getattr(v,'timecode_overlay',None)
        if overlay: overlay.cancel_drag()
        wipe=getattr(v,'wipe_interaction',None)
        if wipe: wipe.dragging=False
        geometry=getattr(v,'geometry_tools',None)
        if geometry:
            geometry.drag=None
            if hasattr(geometry,'frame'): geometry.frame.drag=None
        v.setCursor(Qt.CursorShape.CrossCursor if drawing and drawing.enabled else Qt.CursorShape.OpenHandCursor)

    def eventFilter(self,obj,event):
        kind=event.type(); v=self.viewer
        drawing=getattr(v,'draw_controller',None)
        if drawing and kind in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease) and event.key() in (Qt.Key.Key_Control,Qt.Key.Key_Shift,Qt.Key.Key_Alt):
            flag={Qt.Key.Key_Control:Qt.KeyboardModifier.ControlModifier,Qt.Key.Key_Shift:Qt.KeyboardModifier.ShiftModifier,Qt.Key.Key_Alt:Qt.KeyboardModifier.AltModifier}[event.key()]
            mods=event.modifiers()|flag if kind==QEvent.Type.KeyPress else event.modifiers()&~flag
            drawing.update_picker_cursor(mods)
        if kind==QEvent.Type.ApplicationDeactivate or (kind in (QEvent.Type.Hide,QEvent.Type.WindowDeactivate) and obj is v.window()):
            self.boundary(True); self.release()
        elif kind==QEvent.Type.Leave and obj is v:
            self.boundary(True)
            if QApplication.mouseButtons()==Qt.MouseButton.NoButton: self.release()
        elif isinstance(obj,QWidget) and kind in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.Enter,QEvent.Type.MouseButtonRelease) and hasattr(event,'globalPosition'):
            inside=(obj is v or v.isAncestorOf(obj)) and obj.window() is v.window()
            outside=not inside or not v.isVisible() or not v.rect().contains(v.mapFromGlobal(event.globalPosition().toPoint()))
            self.boundary(outside)
            if not outside and drawing and QApplication.mouseButtons()==Qt.MouseButton.NoButton:
                drawing.update_picker_cursor(event.modifiers() if hasattr(event,'modifiers') else QApplication.keyboardModifiers())
            if kind==QEvent.Type.MouseButtonRelease and outside: self.release()
            elif kind==QEvent.Type.MouseMove and event.buttons()==Qt.MouseButton.NoButton and (v.nav or v.origin is not None): self.release()
        return False
