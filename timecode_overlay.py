# SPDX-License-Identifier: GPL-3.0-only
import math
from PySide6.QtCore import QObject,QEvent,Qt,QPointF,QRectF,Signal
from PySide6.QtGui import QColor,QFont,QFontMetricsF
from ui_text import tr


class TimecodeOverlay(QObject):
    visibilityChanged=Signal(bool)
    positionChanged=Signal()
    lockChanged=Signal(bool)

    def __init__(self,viewer):
        super().__init__(viewer); self.viewer=viewer; self.visible=True; self.locked=False
        self.anchor=QPointF(.5,1); self.time='00:00:00.000'; self.frame=''
        self.drag=None; self.font=QFont('Consolas'); self.font.setPixelSize(12)
        self.small_font=QFont('Segoe UI'); self.small_font.setPixelSize(10)

    def isHidden(self): return not self.visible
    def setVisible(self,visible):
        visible=bool(visible)
        if visible==self.visible: return
        self.visible=visible; self.cancel_drag(); self.viewer.update(); self.visibilityChanged.emit(visible)

    def set_position(self,value):
        if not isinstance(value,(list,tuple)) or len(value)!=2: return
        try:
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in value): return
        except OverflowError: return
        point=QPointF(*(max(0.,min(1.,v)) for v in value))
        if point==self.anchor: return
        self.anchor=point; self.viewer.update(); self.positionChanged.emit()

    def position(self): return [self.anchor.x(),self.anchor.y()]

    def set_locked(self,locked):
        locked=bool(locked)
        if locked==self.locked: return
        self.locked=locked; self.cancel_drag(); self.lockChanged.emit(locked)

    def set_frame(self,frame,total,fps):
        ms=round(frame/float(fps)*1000)
        self.time=f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'
        self.frame=tr(f'IMAGE {frame} / {max(0,total-1)}'+(' · FIN' if total and frame==total else ''))
        self.viewer.update()

    def bounds(self):
        v=self.viewer
        if not v.image: return QRectF()
        return QRectF(v.rect()).adjusted(8,8,-8,-8)

    def rect(self):
        area=self.bounds()
        if not self.visible or area.width()<80 or area.height()<24: return QRectF()
        width=min(area.width(),QFontMetricsF(self.font).horizontalAdvance(self.time)+QFontMetricsF(self.small_font).horizontalAdvance(self.frame)+24)
        height=22.
        return QRectF(area.left()+(area.width()-width)*self.anchor.x(),area.top()+(area.height()-height)*self.anchor.y(),width,height)

    def paint(self,p):
        rect=self.rect()
        if rect.isEmpty(): return
        p.save(); p.resetTransform(); p.setOpacity(.78)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(12,15,20,110)); p.drawRoundedRect(rect,3,3)
        p.setClipRect(rect); p.setFont(self.font); p.setPen(QColor('#e0e3e7'))
        width=QFontMetricsF(self.font).horizontalAdvance(self.time)
        p.drawText(rect.adjusted(7,0,0,0),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,self.time)
        p.setFont(self.small_font); p.setPen(QColor('#b9bec5'))
        p.drawText(rect.adjusted(width+17,0,-7,0),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,self.frame)
        p.restore()

    def cancel_drag(self):
        if self.drag: self.viewer.setCursor(self.drag[1]); self.drag=None

    def eventFilter(self,obj,event):
        kind=event.type()
        if not self.locked and kind==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position()):
            self.drag=(event.position()-self.rect().topLeft(),self.viewer.cursor())
            self.viewer.setCursor(Qt.CursorShape.SizeAllCursor); event.accept(); return True
        if self.drag and kind in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonRelease):
            if kind==QEvent.Type.MouseMove:
                area=self.bounds(); rect=self.rect(); offset=event.position()-self.drag[0]-area.topLeft()
                self.set_position([offset.x()/max(1,area.width()-rect.width()),offset.y()/max(1,area.height()-rect.height())])
            else:
                self.cancel_drag()
            event.accept(); return True
        if self.drag and kind in (QEvent.Type.Hide,QEvent.Type.FocusOut,QEvent.Type.WindowDeactivate):
            self.cancel_drag()
        return False
