# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent,Qt,QRectF
from PySide6.QtGui import QTransform
from ui_text import tr


def working_area(rect,position,swapped):
    area=QRectF(rect); x=rect.left()+rect.width()*position
    if swapped: area.setLeft(x)
    else: area.setRight(x)
    return area


class WipeInteraction(QObject):
    def __init__(self,viewer):
        super().__init__(viewer); self.viewer=viewer; self.dragging=False; viewer.wipe_interaction=self; viewer.installEventFilter(self)
        self.focus_handle=None
        viewer.setFocusPolicy(Qt.StrongFocus)
    def focus_valid(self):
        v=self.viewer
        return bool(v.image and v.comparing and v.compare_mode=='wipe' and v.reference_rgb is not None and not getattr(getattr(v,'geometry_tools',None),'mode',None))
    def activate(self):
        if self.focus_handle is None:
            from handle_focus import HandleFocus
            self.focus_handle=HandleFocus(self.viewer,self.focus_valid,self.nudge,cancel=self.revert)
        self.before=self.viewer.wipe_position
        self.focus_handle.activate(tr('Révélateur'))
    def nudge(self,amount):
        v=self.viewer
        v.wipe_position=min(1,max(0,round(v.wipe_position+amount*.02,8))); v.update()
    def revert(self):
        self.viewer.wipe_position=self.before; self.viewer.update()
    def cancel_drag(self):
        self.dragging=False
        self.viewer.wipe_position=self.drag_position
        self.viewer.setCursor(Qt.CrossCursor if self.viewer.draw_controller.enabled else Qt.OpenHandCursor)
        self.viewer.update()
    def position(self,point):
        v=self.viewer; size=v.image_size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio)
        transform=QTransform(); transform.translate(v.width()/2+v.pan.x(),v.height()/2+v.pan.y()); transform.rotate(v.angle); transform.scale(v.zoom,v.zoom)
        local=transform.inverted()[0].map(point)
        return (local.x()+size.width()/2)/size.width(),local.y(),size
    def eventFilter(self,obj,event):
        v=self.viewer; kind=event.type()
        if not v.image or not v.comparing or v.compare_mode!='wipe': self.dragging=False; return False
        if kind in (QEvent.ShortcutOverride,QEvent.KeyPress) and v.hasFocus() and self.focus_valid():
            if event.key() in (Qt.Key_Return,Qt.Key_Enter) and event.modifiers()==Qt.NoModifier:
                if kind==QEvent.KeyPress: self.activate()
                event.accept(); return True
        if kind not in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.MouseButtonRelease): return False
        x,y,size=self.position(event.position()); hit=abs(x-v.wipe_position)*size.width()*v.zoom<=10 and abs(y)<=size.height()/2
        if kind==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and hit:
            self.dragging=True; self.start_position=event.position(); self.drag_position=v.wipe_position; v.setFocus(Qt.MouseFocusReason); v.setCursor(Qt.CursorShape.SizeHorCursor); event.accept(); return True
        if self.dragging:
            if kind==QEvent.Type.MouseMove:
                v.wipe_position=max(0,min(1,x)); v.update()
            elif kind==QEvent.Type.MouseButtonRelease:
                self.dragging=False; v.setCursor(Qt.CursorShape.CrossCursor if v.draw_controller.enabled else Qt.CursorShape.OpenHandCursor)
                if self.focus_valid() and (event.position()-self.start_position).manhattanLength()<3: self.activate()
            event.accept(); return True
        return False
