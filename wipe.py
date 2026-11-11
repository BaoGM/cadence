# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent,Qt,QRectF
from PySide6.QtGui import QTransform


def working_area(rect,position,swapped):
    area=QRectF(rect); x=rect.left()+rect.width()*position
    if swapped: area.setLeft(x)
    else: area.setRight(x)
    return area


class WipeInteraction(QObject):
    def __init__(self,viewer):
        super().__init__(viewer); self.viewer=viewer; self.dragging=False; viewer.wipe_interaction=self; viewer.installEventFilter(self)
    def position(self,point):
        v=self.viewer; size=v.image_size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio)
        transform=QTransform(); transform.translate(v.width()/2+v.pan.x(),v.height()/2+v.pan.y()); transform.rotate(v.angle); transform.scale(v.zoom,v.zoom)
        local=transform.inverted()[0].map(point)
        return (local.x()+size.width()/2)/size.width(),local.y(),size
    def eventFilter(self,obj,event):
        v=self.viewer; kind=event.type()
        if not v.image or not v.comparing or v.compare_mode!='wipe': self.dragging=False; return False
        if kind not in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseMove,QEvent.Type.MouseButtonRelease): return False
        x,y,size=self.position(event.position()); hit=abs(x-v.wipe_position)*size.width()*v.zoom<=10 and abs(y)<=size.height()/2
        if kind==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and hit:
            self.dragging=True; v.setCursor(Qt.CursorShape.SizeHorCursor); event.accept(); return True
        if self.dragging:
            if kind==QEvent.Type.MouseMove:
                v.wipe_position=max(0,min(1,x)); v.update()
            elif kind==QEvent.Type.MouseButtonRelease:
                self.dragging=False; v.setCursor(Qt.CursorShape.CrossCursor if v.draw_controller.enabled else Qt.CursorShape.OpenHandCursor)
            event.accept(); return True
        return False
