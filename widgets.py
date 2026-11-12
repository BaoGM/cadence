# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from ui_text import tr
import math
import numpy as np
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QEvent, QVariantAnimation, QEasingCurve, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QImage, QPainterPath, QPolygonF
from PySide6.QtWidgets import QWidget, QDoubleSpinBox, QSpinBox, QMenu, QPushButton
from media import exposure_lut
from model import locate
from drag import ContinuousDrag
from drawing_timeline import DrawingTimeline
from preferences import default_canvas, modifier_name

BG=QColor('#101318'); PANEL=QColor('#191e26'); MUTED=QColor('#8895a7'); TEXT=QColor('#e8edf5'); ACCENT=QColor('#68e0cf')
TRANSPORT_ICON_HEIGHT = 20.0

def paint_frame_number(p,frame,center,y,bounds,active=False):
    p.save(); p.resetTransform(); p.setClipping(False); p.setFont(QFont('Segoe UI',11,QFont.Weight.Bold) if active else QFont('Segoe UI',8))
    text=str(frame); width=p.fontMetrics().horizontalAdvance(text)+10
    height=p.fontMetrics().height()+2
    x=max(bounds.left(),min(center-width/2,bounds.right()-width))
    y=max(bounds.top(),min(y,bounds.bottom()-height))
    area=QRectF(x,y,width,height)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(12,15,20,205)); p.drawRoundedRect(area,3,3)
    p.setPen(QColor('#ffffff') if active else QColor('#b8c3d1')); p.drawText(area,Qt.AlignmentFlag.AlignCenter,text); p.restore()
    return area

class ScrubMixin:
    def init_scrub(self):
        self.scrubbing=False; self._press=None
        self.setStyleSheet('QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {width:0px;height:0px;border:none;}')
        self.lineEdit().setTextMargins(6,0,6,0)
        self.setKeyboardTracking(False)
        self.lineEdit().installEventFilter(self)
        self.lineEdit().setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip(tr('Cliquer pour saisir · Entrée : valider · Glisser pour régler · Maj : précision'))
    def eventFilter(self,obj,event):
        if obj is self.lineEdit():
            if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
                self.interpretText()
                self._press=event.globalPosition().x(); self._value_drag=ContinuousDrag(event.globalPosition()); self._base=self.value(); self.scrubbing=False
            elif event.type()==QEvent.Type.MouseMove and self._press is not None:
                dx=self._value_drag.move(event.globalPosition()).x()
                if abs(dx)>=3 or self.scrubbing:
                    self.scrubbing=True
                    factor=.1 if event.modifiers()&Qt.KeyboardModifier.ShiftModifier else 1
                    value=self._base+dx/10*self.singleStep()*factor
                    self.setValue(round(value) if isinstance(self,QSpinBox) else value)
                    return True
            elif event.type()==QEvent.Type.MouseButtonRelease and self._press is not None:
                dragged=self.scrubbing; self._press=None; self.scrubbing=False; self._value_drag.finish()
                if dragged: self.editingFinished.emit(); return True
                self.selectAll(); return True
            elif event.type()==QEvent.Type.MouseButtonDblClick:
                if self._press is not None: self._value_drag.finish()
                self._press=None; self.scrubbing=False
                self.selectAll(); return True
        return super().eventFilter(obj,event)

class ScrubDoubleSpinBox(ScrubMixin,QDoubleSpinBox):
    def __init__(self): super().__init__(); self.init_scrub()

class ScrubSpinBox(ScrubMixin,QSpinBox):
    def __init__(self): super().__init__(); self.init_scrub()

class TransportButton(QPushButton):
    def __init__(self,symbol,callback,name='transport',tip=''):
        super().__init__(''); self.symbol=symbol; self.setObjectName(name); self.setFixedSize(36,34)
        self.setStyleSheet('QPushButton { background: transparent; border: none; padding:0; min-width:36px; max-width:36px; min-height:34px; max-height:34px; }')
        self.clicked.connect(callback); self.setToolTip(tr(tip)); self.setAccessibleName(tr(tip))
    def setSymbol(self,symbol): self.symbol=symbol; self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown():
            area=QRectF(self.rect()).adjusted(2,2,-2,-2)
            p.setPen(QPen(QColor('#080d12'),1)); p.setBrush(QColor('#0b1016')); p.drawRoundedRect(area,6,6)
            p.setPen(QPen(QColor('#293540'),1)); p.drawLine(area.bottomLeft(),area.bottomRight())
        p.translate(self.width()/2,self.height()/2-3+(1 if self.isDown() else 0))
        color=QColor('#68e0cf') if self.objectName()=='primary' else TEXT
        if self.isDown(): color=QColor('#a6fff1')
        if not self.isEnabled(): color=MUTED
        pen=QPen(color,2.2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.SquareCap,Qt.PenJoinStyle.MiterJoin); p.setPen(pen)
        scale=TRANSPORT_ICON_HEIGHT/24.0; p.scale(scale,scale); self.draw_symbol(p,color)
        p.end()
    def draw_symbol(self,p,color):
        path=QPainterPath(); symbol=self.symbol
        if symbol=='play':
            path.moveTo(-6,-10); path.lineTo(8,0); path.lineTo(-6,10); path.closeSubpath(); p.fillPath(path,color)
        elif symbol=='pause':
            p.drawLine(QPointF(-5,-9),QPointF(-5,9)); p.drawLine(QPointF(5,-9),QPointF(5,9))
        elif symbol in ('first','previous','next','last'):
            if symbol in ('first','previous'): p.scale(-1,1)
            path.moveTo(-5,-8); path.lineTo(4,0); path.lineTo(-5,8); p.drawPath(path)
            if symbol in ('first','last'): p.drawLine(QPointF(10,-9),QPointF(10,9))
        elif symbol=='loop':
            path.moveTo(10,2); path.lineTo(10,8); path.lineTo(7,11); path.lineTo(-7,11); path.lineTo(-10,8); path.lineTo(-10,-4); path.lineTo(-7,-7); path.lineTo(10,-7); p.drawPath(path)
            path=QPainterPath(); path.moveTo(5,-12); path.lineTo(10,-7); path.lineTo(5,-2); p.drawPath(path)
        else:
            p.drawLine(QPointF(-11,0),QPointF(11,0)); path.moveTo(4,-7); path.lineTo(11,0); path.lineTo(4,7); p.drawPath(path)

class VolumeBars(QWidget):
    valueChanged=Signal(int)
    mutedChanged=Signal(bool)
    def __init__(self):
        super().__init__(); self._value=80; self.muted=False; self.dragging=False
        self.setFixedSize(104,42); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr('Volume de lecture')); self.update_tip()
    def value(self): return self._value
    def setValue(self,value):
        value=max(0,min(100,int(value)))
        if value!=self._value: self._value=value; self.valueChanged.emit(value)
        self.update_tip(); self.update()
    def setMuted(self,muted):
        muted=bool(muted)
        if self.muted!=muted: self.muted=muted; self.mutedChanged.emit(muted)
        self.update_tip(); self.update()
    def update_tip(self): self.setToolTip(tr(f'Volume : {self._value} %'+(' · Muet' if self.muted else '')+'\nGlisser : volume · Clic droit : Mute / Unmute'))
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left=7; width=self.width()-14; gap=7; bar=(width-5*gap)/6
        bottom=(self.height()+14)/2
        for i in range(6):
            height=8+i*3.4; area=QRectF(left+i*(bar+gap),bottom-height,bar,height)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#344354')); p.drawRoundedRect(area,.6,.6)
            fraction=max(0,min(1,self._value/100*6-i))
            if fraction:
                p.save(); p.setClipRect(QRectF(area.x(),area.y(),area.width()*fraction,area.height())); p.setBrush(QColor("#697580") if self.muted else ACCENT); p.drawRoundedRect(area,.6,.6); p.restore()
        p.end()
    def set_from_x(self,x): self.setValue(round((x-7)/max(1,self.width()-14)*100))
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.dragging=True; self.setFocus(); self.set_from_x(event.position().x())
    def mouseMoveEvent(self,event):
        if self.dragging: self.set_from_x(event.position().x())
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.dragging=False
    def wheelEvent(self,event): self.setValue(self.value()+round(event.angleDelta().y()/120)*5); event.accept()
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Down): self.setValue(self.value()-5)
        elif event.key() in (Qt.Key.Key_Right,Qt.Key.Key_Up): self.setValue(self.value()+5)
        elif event.key()==Qt.Key.Key_Home: self.setValue(0)
        elif event.key()==Qt.Key.Key_End: self.setValue(100)
        elif event.key()==Qt.Key.Key_M: self.setMuted(not self.muted)
        else: super().keyPressEvent(event)
    def contextMenuEvent(self,event):
        menu=QMenu(tr(self)); action=menu.addAction(tr('Unmute' if self.muted else 'Mute')); action.triggered.connect(lambda:self.setMuted(not self.muted)); menu.exec(event.globalPos())

class Viewer(QWidget):
    scrub=Signal(int)
    scrubStarted=Signal()
    scrubActiveChanged=Signal(bool)
    fileDropped=Signal(list)
    fullscreenRequested=Signal()
    openRequested=Signal()
    def __init__(self):
        super().__init__(); self.setMinimumSize(160,90); self.setAcceptDrops(True)
        self.reference_rgb=None; self.comparing=False; self.compare_mode='horizontal'; self.compare_opacity=.5; self.compare_gain=1.; self.compare_swapped=False; self.wipe_position=.5; self.wipe_image=None
        self.rgb=None; self.image=None; self.ev=0; self.origin=None; self.base=0; self.position=0; self.loaded=False
        self.gpu_packet=None; self._cpu_preview=None
        self.zoom=1.0; self.pan=QPointF(0,0); self.angle=0.0; self.nav=None; self.controls=default_canvas()
        self.scrub_pixels=4.0; self.flip_h=False; self.flip_v=False
        from viewer_cursor import ViewerCursor
        self.cursor_guard=ViewerCursor(self)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        from video_surface import attach_surface
        attach_surface(self)
    def update(self,*args):
        super().update(*args)
        if getattr(self,'surface',None) is not None: self.surface.update()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.surface is not None: self.surface.setGeometry(self.rect())
    def showEvent(self,event):
        super().showEvent(event)
        self.cursor_guard.activate()
        if self.graphics_startup is not None: self.graphics_startup.schedule()
    def hideEvent(self,event):
        self.cursor_guard.deactivate(); super().hideEvent(event)
    def set_frame(self,arr):
        self.rgb=arr; self.loaded=True; self.apply_effect()
    def set_exposure(self,ev): self.ev=ev; self.apply_effect()
    def apply_effect(self):
        if self.rgb is not None:
            signature=(id(self.rgb),id(self.reference_rgb),self.ev,self.flip_h,self.flip_v,self.comparing,self.compare_mode,self.compare_opacity,self.compare_gain,self.compare_swapped,getattr(self,'geometry_segment',None),getattr(self,'geometry_aspect',None),getattr(self,'geometry_source',False))
            if signature==getattr(self,'_effect_signature',None): return
            from clip_geometry import apply_geometry
            from native_render import rgb_image
            prepared=apply_geometry(self.rgb,getattr(self,'geometry_segment',None),getattr(self,'geometry_aspect',None),getattr(self,'geometry_source',False))
            comparing=self.comparing and self.reference_rgb is not None
            self.gpu_packet=None; self._cpu_preview=None
            if self.renderer in ('opengl','direct3d') and self.surface is not None and not self.surface.compositor.failed:
                if self.renderer=='direct3d': from native_d3d import prepare
                else: from native_gpu import prepare
                self.gpu_packet=prepare(prepared,self.reference_rgb if comparing else None,
                    ev=self.ev,mode=self.compare_mode if comparing else 'single',opacity=self.compare_opacity,
                    gain=self.compare_gain,swapped=self.compare_swapped,flip_h=self.flip_h,flip_v=self.flip_v,wipe=self.wipe_position)
            if self.gpu_packet is not None:
                storage=self.gpu_packet[0][0]
                self.image=QImage(storage.data,storage.shape[1],storage.shape[0],storage.strides[0],QImage.Format.Format_RGB888)
                self.wipe_image=None; self._effect_signature=signature; self._effect_sources=(self.rgb,self.reference_rgb)
                self.update(); return
            native_image=rgb_image(prepared,self.reference_rgb if comparing else None,
                ev=self.ev,mode=self.compare_mode if comparing else 'single',
                opacity=self.compare_opacity,gain=self.compare_gain,swapped=self.compare_swapped,
                flip_h=self.flip_h,flip_v=self.flip_v)
            if native_image is not None:
                self.image=native_image; self.wipe_image=None
                self._effect_signature=signature; self._effect_sources=(self.rgb,self.reference_rgb)
                self.update(); return
            def effect(rgb):
                if self.ev: rgb=exposure_lut(self.ev)[rgb]
                if self.flip_h: rgb=rgb[:,::-1]
                if self.flip_v: rgb=rgb[::-1]
                return rgb
            rgb=effect(prepared)
            self.wipe_image=None
            if self.comparing and self.reference_rgb is not None:
                from comparison import compose,fit_reference
                if self.compare_mode=='wipe':
                    other=fit_reference(effect(self.reference_rgb),rgb.shape[1],rgb.shape[0])
                    if self.compare_swapped: rgb,other=other,rgb
                    other=np.ascontiguousarray(other)
                    self.wipe_image=QImage(other.data,other.shape[1],other.shape[0],other.strides[0],QImage.Format.Format_RGB888).copy()
                else: rgb=compose(rgb,effect(self.reference_rgb),self.compare_mode,self.compare_opacity,self.compare_gain,self.compare_swapped)
            rgb=np.ascontiguousarray(rgb)
            self.image=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888).copy()
            self._effect_signature=signature; self._effect_sources=(self.rgb,self.reference_rgb)
        self.update()
    def image_size(self):
        size=self.image.size()
        if self.gpu_packet is not None:
            if self.compare_mode=="horizontal" and self.comparing: size.setWidth(size.width()*2)
            elif self.compare_mode=="vertical" and self.comparing: size.setHeight(size.height()*2)
        return size
    def cpu_preview(self):
        if self.gpu_packet is None: return self.image
        if self._cpu_preview is None or (self.comparing and self.compare_mode=='wipe' and getattr(self,'_cpu_wipe',None)!=self.wipe_position):
            self._cpu_wipe=self.wipe_position
            from native_render import rgb_image
            arrays=self.gpu_packet[0]
            image=rgb_image(arrays[0],arrays[1] if len(arrays)>1 else None,
                ev=self.ev,mode=self.compare_mode if len(arrays)>1 else 'single',opacity=self.compare_opacity,
                gain=self.compare_gain,swapped=self.compare_swapped,flip_h=self.flip_h,flip_v=self.flip_v)
            if image is None:
                def effect(rgb):
                    if self.ev: rgb=exposure_lut(self.ev)[rgb]
                    if self.flip_h: rgb=rgb[:,::-1]
                    if self.flip_v: rgb=rgb[::-1]
                    return rgb
                rgb=effect(arrays[0])
                if len(arrays)>1:
                    from comparison import compose
                    rgb=compose(rgb,effect(arrays[1]),self.compare_mode,self.compare_opacity,self.compare_gain,self.compare_swapped,self.wipe_position)
                rgb=np.ascontiguousarray(rgb)
                image=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888).copy()
            self._cpu_preview=image
        return self._cpu_preview
    def clear(self): self._effect_signature=None; self._effect_sources=None; self.gpu_packet=None; self._cpu_preview=None; self.reference_rgb=None; self.rgb=None; self.image=None; self.loaded=False; self.update()
    def paintEvent(self,event):
        if self.renderer in ('opengl','direct3d'): return
        p=QPainter(self)
        try: self.paint_scene(p)
        finally: p.end()
    def paint_scene(self,p,video_draw=None,sample=False,drawing_draw=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if video_draw is None: p.fillRect(self.rect(),QColor('#0c0f14'))
        if self.image:
            size=self.image_size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            area=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); p.translate(self.width()/2+self.pan.x(),self.height()/2+self.pan.y()); p.rotate(self.angle); p.scale(self.zoom,self.zoom)
            image_rect=QRectF(-size.width()/2,-size.height()/2,size.width(),size.height())
            if self.gpu_packet is not None: self.gpu_packet.wipe=self.wipe_position
            accelerated=False if sample else video_draw(p,image_rect) if video_draw else self.gpu_packet is not None and self.surface is not None and self.surface.compositor.paint(p,self.gpu_packet,image_rect)
            if not accelerated: p.drawImage(image_rect,self.cpu_preview())
            wiping=self.comparing and self.reference_rgb is not None and self.compare_mode=='wipe'
            if wiping:
                area=QRectF(-size.width()/2,-size.height()/2,size.width(),size.height()); x=area.left()+area.width()*self.wipe_position
                if self.wipe_image is not None:
                    p.save(); p.setClipRect(QRectF(x,area.top(),area.right()-x,area.height())); p.drawImage(area,self.wipe_image); p.restore()
            p.save()
            if wiping:
                from wipe import working_area
                p.setClipRect(working_area(area,self.wipe_position,self.compare_swapped),Qt.ClipOperation.IntersectClip)
            if hasattr(self,'draw_controller'): self.draw_controller.paint(p,size,adornments=not sample,layer_draw=drawing_draw,accelerated=accelerated and not sample)
            if not sample and hasattr(self,'geometry_tools'): self.geometry_tools.paint(p,size)
            p.restore()
            if wiping and not sample:
                p.setPen(QPen(QColor('#ffffff'),1.5/self.zoom)); p.drawLine(QPointF(x,area.top()),QPointF(x,area.bottom()))
                self.paint_wipe_handle(p,x)
            if self.comparing and not sample:
                p.resetTransform(); p.setPen(ACCENT); p.setFont(QFont('Segoe UI',10,QFont.Weight.DemiBold))
                first,second=('B','A') if self.compare_swapped else ('A','B')
                text={'horizontal':f'{first}  |  {second}','vertical':f'{first} en haut / {second} en bas','overlay':f'Overlay {first} + {second}','difference':'Différence |A − B|','wipe':f'{first} | {second}', 'front':f'{first} au premier plan'}.get(self.compare_mode,'')
                p.fillRect(QRectF(8,8,260,24),QColor(12,15,20,210)); p.drawText(QRectF(14,8,250,24),Qt.AlignmentFlag.AlignVCenter,tr(text))
        else:
            cx,cy=self.width()/2,self.height()/2
            scale=max(2,math.ceil(self.devicePixelRatioF()*2))
            if getattr(self,'_welcome_scale',None)!=scale:
                self._welcome_scale=scale
                self._welcome_icon=QImage(84*scale,68*scale,QImage.Format.Format_ARGB32_Premultiplied); self._welcome_icon.fill(Qt.GlobalColor.transparent)
                icon=QPainter(self._welcome_icon); icon.setRenderHint(QPainter.RenderHint.Antialiasing); icon.scale(scale,scale)
                icon.setPen(QPen(QColor('#27303b'),1)); icon.setBrush(QColor('#141a22')); icon.drawRoundedRect(QRectF(1,1,82,66),14,14)
                icon.setBrush(ACCENT); icon.setPen(Qt.PenStyle.NoPen)
                path=QPainterPath(); path.moveTo(33,18); path.lineTo(57,34); path.lineTo(33,50); path.closeSubpath(); icon.drawPath(path); icon.end()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(QRectF(cx-42,cy-55,84,68),self._welcome_icon)
            p.setPen(MUTED); p.setFont(QFont('Segoe UI',10))
            p.drawText(QRectF(0,cy+30,self.width(),28),Qt.AlignmentFlag.AlignCenter,tr('Double-cliquez pour ouvrir une vidéo et commencer votre montage.'))
        if not sample and hasattr(self,'timecode_overlay'): self.timecode_overlay.paint(p)
    def sample_color(self,point):
        if self.image is None or not self.rect().contains(point.toPoint()): return None
        image=QImage(1,1,QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#0c0f14')); painter=QPainter(image)
        painter.translate(-math.floor(point.x()),-math.floor(point.y()))
        try: self.paint_scene(painter,sample=True)
        finally: painter.end()
        return image.pixelColor(0,0).name()
    def paint_wipe_handle(self,p,x):
        scale=max(4,math.ceil(self.devicePixelRatioF()*4))
        if getattr(self,'_wipe_handle_scale',None)!=scale:
            self._wipe_handle_scale=scale
            self._wipe_handle=QImage(14*scale,22*scale,QImage.Format.Format_ARGB32_Premultiplied); self._wipe_handle.fill(Qt.GlobalColor.transparent)
            icon=QPainter(self._wipe_handle); icon.setRenderHint(QPainter.RenderHint.Antialiasing); icon.scale(scale,scale)
            icon.setPen(QPen(QColor('#ffffff'),1.5)); icon.setBrush(ACCENT); icon.drawEllipse(QRectF(2,2,10,18)); icon.end()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(x-7/self.zoom,-11/self.zoom,14/self.zoom,22/self.zoom),self._wipe_handle)
    def reset_view(self): self.zoom=1.0; self.pan=QPointF(0,0); self.angle=0.0; self.update()
    def zoom_by(self,factor): self.zoom=max(.05,min(30,self.zoom*factor)); self.update()
    def wheelEvent(self,e):
        if self.loaded: self.zoom_by(1.2**(e.angleDelta().y()/120)); e.accept()
    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.MiddleButton:
            mode=next((name for name,config in self.controls.items() if config['modifiers']==modifier_name(e.modifiers())),None)
            if mode:
                self.nav=(mode,e.position(),QPointF(self.pan),self.angle,self.zoom); self._canvas_drag=ContinuousDrag(e.globalPosition(),'xy' if mode=='pan' else self.controls[mode]['axis'])
            e.accept(); return
        if e.button()==Qt.MouseButton.LeftButton and self.loaded:
            self.scrubStarted.emit(); self.origin=e.position().x(); self.base=self.position; self._video_drag=ContinuousDrag(e.globalPosition())
            self.scrubActiveChanged.emit(True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
    def mouseMoveEvent(self,e):
        if self.nav:
            mode,start,pan,angle,zoom=self.nav; delta=self._canvas_drag.move(e.globalPosition())
            config=self.controls[mode]; dx=delta.x()*(-1 if config['invert_x'] else 1); dy=delta.y()*(-1 if config['invert_y'] else 1); amount=dx if config['axis']=='x' else dy
            if mode=='rotate': self.angle=angle+amount*.5
            elif mode=='zoom': self.zoom=max(.05,min(30,zoom*math.exp(max(-10,min(10,amount*.008)))))
            else: self.pan=pan+QPointF(dx,dy)
            self.update(); return
        if self.origin is not None:
            divisor=self.scrub_pixels*(3 if e.modifiers()&Qt.KeyboardModifier.ShiftModifier else 1)
            self.scrub.emit(self.base+int(self._video_drag.move(e.globalPosition()).x()/divisor))
    def finish_navigation(self,restore=True):
        if self.nav: self._canvas_drag.finish(restore=restore)
        if self.origin is not None: self._video_drag.finish(restore=restore); self.scrubActiveChanged.emit(False)
        self.nav=None; self.origin=None; self.setCursor(Qt.CursorShape.CrossCursor if getattr(getattr(self,'draw_controller',None),'enabled',False) else Qt.CursorShape.OpenHandCursor)
    def mouseReleaseEvent(self,e): self.finish_navigation()
    def setCursor(self,cursor):
        if hasattr(self,'cursor_guard'): self.cursor_guard.set_cursor(cursor)
        else: super().setCursor(cursor)
    def mouseDoubleClickEvent(self,e):
        if not self.loaded: self.openRequested.emit()
        else: self.fullscreenRequested.emit()
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self,e):
        urls=e.mimeData().urls()
        paths=[u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths: self.fileDropped.emit(paths)

class Timeline(QWidget):
    cadenceRequested=Signal(int,int)
    scrubStarted=Signal()
    scrubFinished=Signal()
    seek=Signal(int)
    selected=Signal(int,int)
    selectionDragged=Signal(int,int,int)
    simpleRequested=Signal(bool)
    moved=Signal(int,int,int,str)
    duplicated=Signal(int,int,int)
    deleteRequested=Signal(int,int,str)
    muteRequested=Signal(int,int,str)
    splitRequested=Signal(str)
    deleteMediaRequested=Signal(int,int)
    viewportChanged=Signal()
    unitsChanged=Signal(str)
    drawingMoved=Signal(int,int,int)
    drawingResized=Signal(int,int,int)
    drawingDelete=Signal(int,int)
    markerAdded=Signal(int)
    markersDeleted=Signal(int,int)
    drawingClipboardRequested=Signal(str,int,int)
    def __init__(self):
        super().__init__(); self.setFocusPolicy(Qt.FocusPolicy.ClickFocus); self.setFixedHeight(100); self.state=None; self.fps=24; self.media={}; self.anchor=None; self.drag=False; self.wave={}
        from timeline_index import SegmentIndex
        self.track_indices={'video':SegmentIndex(),'audio':SegmentIndex()}
        self.simple=False; self.selection_track='video'; self.drawing_track=DrawingTimeline(self)
        self.zoom=1.; self.view_start=0.; self.nav=None; self.hover_x=None; self.external_scrubbing=False
        self.units='time'; self.gesture=None; self.move_span=None; self.drop_frame=None; self.ghost_x=None; self.animated_x=None; self.linked=True; self.leave_gap=False
        self.drag_animation=QVariantAnimation(self); self.drag_animation.setDuration(110); self.drag_animation.setEasingCurve(QEasingCurve.Type.OutCubic); self.drag_animation.valueChanged.connect(self.animate_drop)
        self.setMouseTracking(True); self.setToolTip(tr('Glisser : scrub · Maj + glisser : sélectionner · Alt + glisser : déplacer · Alt + Maj + glisser : dupliquer avec le son'))
    def animate_drop(self,value): self.animated_x=float(value); self.update()
    def target_drop(self,x):
        target=self.boundary_for(x)
        if target!=self.drop_frame:
            self.drop_frame=target; end=self.x_for(target)
            self.drag_animation.stop(); self.drag_animation.setStartValue(self.animated_x if self.animated_x is not None else end); self.drag_animation.setEndValue(end); self.drag_animation.start()
        self.ghost_x=x-self.grab_offset; self.update()
    def set_document(self,state,media,fps):
        self.state=state; self.setFixedHeight(44 if getattr(self,"simple",False) else 100); self.media=media; self.fps=float(fps); self.clamp_view(); self.update()
    def set_units(self,units):
        self.units=units; self.update(); self.unitsChanged.emit(units)
    def tick_label(self,frame):
        if self.units=='frames': return str(frame)
        ms=round(frame/self.fps*1000)
        return f'{ms//60000:02}:{ms//1000%60:02}.{ms%1000:03}'
    def span(self): return max(1,(self.state.length if self.state else 1)/self.zoom)
    def ensure_visible(self,frame):
        if not self.state or self.zoom<=1: return
        span=self.span()
        if frame<self.view_start or frame>=self.view_start+span:
            self.view_start=frame-span*.1 if frame>=self.view_start+span else frame-span*.9
            self.clamp_view(); self.update()
    def clamp_view(self): self.view_start=max(0,min(self.view_start,max(0,(self.state.length if self.state else 0)-self.span()))); self.viewportChanged.emit()
    def reset_view(self): self.zoom=1.; self.view_start=0.; self.clamp_view(); self.update()
    def track_y(self,track): return {'video':47,'audio':73,'drawing':40}[track]
    def track_rect(self,track): return QRectF(self.track_left(),self.track_y(track),self.track_width(),19)
    def simple_track_rect(self): return QRectF(self.track_left(),24,self.track_width(),12)
    def track_left(self): return 20 if getattr(self,'simple',False) else 78
    def track_right(self): return self.width()-self.track_left()
    def track_width(self): return max(1,self.track_right()-self.track_left())
    def raw_frame(self,x): return self.view_start+(x-self.track_left())/self.track_width()*self.span()
    def x_for(self,frame): return self.track_left()+(frame-self.view_start)/self.span()*self.track_width()
    def frame_for(self,x): return max(0,min(self.state.length-1,int(self.raw_frame(x))))
    def hover_frame(self):
        if self.hover_x is None or not self.state or not self.state.length or self.anchor is not None or self.nav or self.drawing_track.mode: return None
        if not self.track_left()<=self.hover_x<=self.track_right(): return None
        return self.frame_for(self.hover_x)
    def set_external_scrubbing(self,active): self.external_scrubbing=active; self.update()
    def frame_indicator(self):
        if not self.state or not self.state.length or self.nav: return None
        if self.external_scrubbing:
            frame=max(0,min(self.state.position,self.state.length-1))
        elif self.gesture in ('scrub','select') or self.drawing_track.mode in ('scrub','select'):
            frame=self.range_frame
        else:
            frame=self.hover_frame()
            return (frame,self.hover_x) if frame is not None else None
        return frame,self.x_for(frame)
    def paint_frame_indicator(self,p):
        if not self.state or not self.state.length: return
        current=max(0,min(self.state.position,self.state.length-1)); x=self.x_for(current)
        bounds=QRectF(self.track_left(),0,self.track_width(),30)
        current_area=None
        if bounds.left()<=x<=bounds.right(): current_area=paint_frame_number(p,self.tick_label(current),x,1,bounds,active=True)
        indicator=self.frame_indicator()
        if indicator is not None:
            frame,hx=indicator
            text=self.tick_label(frame)
            p.save(); p.setFont(QFont('Segoe UI',8)); width=p.fontMetrics().horizontalAdvance(text)+10; p.restore()
            left=max(bounds.left(),min(hx-width/2,bounds.right()-width))
            area=QRectF(left,3,width,24)
            if frame!=current and (current_area is None or not current_area.adjusted(-5,0,5,0).intersects(area)):
                paint_frame_number(p,text,hx,3,bounds)
    def paint_current_highlight(self,p,bar_path=None):
        if not self.state or not self.state.length: return
        frame=max(0,min(self.state.position,self.state.length-1))
        left=self.track_left(); right=left+self.track_width(); x=self.x_for(frame)
        if not left<=x<=right: return
        width=max(3,self.x_for(frame+1)-x)
        bar=self.simple_track_rect()
        y,h=(bar.top()-2,bar.height()+4) if getattr(self,'simple',False) else (42,self.height()-46)
        p.save(); p.setClipRect(QRectF(left,y,right-left,h))
        if bar_path is not None: p.setClipPath(bar_path,Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(x,y,width,h),QColor(255,255,255,125 if getattr(self,'simple',False) else 65)); p.restore()
    def paint_hover_highlight(self,p,bar_path=None):
        frame=self.hover_frame()
        if frame is None or self.external_scrubbing: return
        left=self.track_left(); right=left+self.track_width()
        x1=max(left,self.x_for(frame)); x2=min(right,max(x1+1,self.x_for(frame+1)))
        if x2<=x1: return
        bar=self.simple_track_rect()
        y,h=(bar.top(),bar.height()) if getattr(self,'simple',False) else (42,self.height()-50)
        p.save(); p.setClipRect(QRectF(left,y,right-left,h))
        if bar_path is not None: p.setClipPath(bar_path,Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(x1,y,x2-x1,h),QColor(217,230,240,48 if getattr(self,'simple',False) else 16)); p.restore()
    def leaveEvent(self,event):
        self.hover_x=None; self.update(); super().leaveEvent(event)
    def wheelEvent(self,e):
        if not self.state or not self.state.length: return
        before=self.raw_frame(e.position().x()); ratio=(e.position().x()-self.track_left())/self.track_width()
        self.zoom=max(1,min(max(1,self.state.length/2),self.zoom*1.3**(e.angleDelta().y()/120)))
        self.view_start=before-ratio*self.span(); self.clamp_view(); self.update(); e.accept()
    def ruler_steps(self):
        import math
        def nice(value):
            power=10**max(0,math.floor(math.log10(max(1,value))))
            return next(m*power for m in (1,2,5,10) if m*power>=value)
        pixels=self.track_width()/max(1,self.span())
        minor=nice(10/max(.000001,pixels))
        major=minor*nice(90/max(.000001,pixels*minor))
        return minor,major
    def paint_ruler(self,p,simple,bar_path=None):
        import math
        minor,major=self.ruler_steps(); left=self.track_left(); right=left+self.track_width()
        end=min(self.state.length,math.ceil(self.view_start+self.span()))
        major_ticks=QPainterPath(); minor_ticks=QPainterPath()
        p.save(); p.setClipRect(QRectF(left,0,self.track_width()+1,38)); p.setFont(QFont('Segoe UI',8))
        for f in range(max(0,math.ceil(self.view_start/minor)*minor),end+1,minor):
            x=self.x_for(f); large=f%major==0
            if simple:
                if 0<f<self.state.length and left<x<right:
                    bar=self.simple_track_rect(); height=bar.height() if large else 5
                    ticks=major_ticks if large else minor_ticks
                    ticks.moveTo(x,bar.center().y()-height/2); ticks.lineTo(x,bar.center().y()+height/2)
            else:
                p.setPen(QColor('#647384' if large else '#3a4653')); p.drawLine(QPointF(x,38-(7 if large else 3)),QPointF(x,38))
            if large:
                p.setPen(MUTED); label=self.tick_label(f); width=p.fontMetrics().horizontalAdvance(label)+8
                p.drawText(QRectF(max(left,min(x-width/2,right-width)),1,width,20),Qt.AlignmentFlag.AlignCenter,tr(label))
        if simple:
            p.save()
            if bar_path is not None: p.setClipPath(bar_path,Qt.ClipOperation.IntersectClip)
            for ticks,width,color in ((minor_ticks,1,'#3a424c'),(major_ticks,2,'#202832')):
                p.setPen(QPen(QColor(color),width,Qt.PenStyle.SolidLine,Qt.PenCapStyle.FlatCap)); p.drawPath(ticks)
            p.restore()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#68e0cf'))
        for f in self.state.frame_markers:
            x=self.x_for(f)
            if left<=x<=right:
                y=self.simple_track_rect().center().y() if simple else 30
                p.drawPolygon(QPolygonF([QPointF(x,y-4),QPointF(x+4,y),QPointF(x,y+4),QPointF(x-4,y)]))
        p.restore()
    def selection_label(self):
        if not self.state or not self.state.selection: return ''
        a,b=self.state.selection
        return str(b-a)+' '+tr('img') if self.units=='frames' else self.tick_label(b-a)
    def paint_selection_label(self,p):
        if not self.state or not self.state.selection: return
        a,b=self.state.selection; left=max(self.track_left(),self.x_for(a)); right=min(self.track_right(),self.x_for(b))
        if right<=left: return
        p.save(); p.setFont(QFont('Segoe UI',8))
        text=self.selection_label(); width=p.fontMetrics().horizontalAdvance(text)+10
        if width>right-left-4: p.restore(); return
        y=self.simple_track_rect().center().y()-7.5 if self.simple else 60
        area=QRectF((left+right-width)/2,y,width,15)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(12,15,20,175)); p.drawRoundedRect(area,2,2)
        p.setPen(QColor(220,232,235,220)); p.drawText(area,Qt.AlignmentFlag.AlignCenter,text); p.restore()
    def media_boundaries(self):
        if not self.state: return []
        positions=[]; last=None
        for _,at,segment in self.track_indices['video'].visible(self.state.segments,self.view_start,self.view_start+self.span()):
            x=self.x_for(at)
            if at and self.track_left()<x<self.track_right() and (last is None or x-last>=3):
                positions.append(x); last=x
        return positions
    def simple_media_path(self):
        bar=self.simple_track_rect(); path=QPainterPath()
        edges=[bar.left(),*self.media_boundaries(),bar.right()]
        for i,(left,right) in enumerate(zip(edges,edges[1:])):
            start=left+(1 if i else 0); end=right-(1 if i<len(edges)-2 else 0)
            if end>start: path.addRoundedRect(QRectF(start,bar.top(),end-start,bar.height()),4,4)
        return path
    def paint_simple_move(self,p):
        if not self.move_span or self.ghost_x is None: return
        a,b,track=self.move_span; left=self.track_left(); right=self.track_right()
        bar=self.simple_track_rect(); p.save(); p.setClipRect(bar.adjusted(0,-3,0,5))
        source=QRectF(self.x_for(a),bar.top(),self.x_for(b)-self.x_for(a),bar.height())
        if self.gesture!='copy': p.fillRect(source,QColor(0,0,0,125))
        width=max(4,min(right-left,self.x_for(b)-self.x_for(a)))
        x=max(left,min(self.ghost_x,right-width))
        p.setPen(QPen(QColor('#ffb35e'),1)); p.setBrush(QColor(215,132,40,205)); p.drawRoundedRect(QRectF(x,bar.top()-2,width,bar.height()+2),3,3)
        if self.drop_frame is not None:
            target=self.animated_x if self.animated_x is not None else self.x_for(self.drop_frame)
            p.setPen(QPen(QColor('#ff963b'),2)); p.drawLine(QPointF(target,bar.top()-3),QPointF(target,bar.bottom()+4))
        p.restore()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.fillRect(self.rect(),QColor('#161b23'))
        if getattr(self,'simple',False):
            bar=self.simple_track_rect(); bar_path=self.simple_media_path()
            p.fillPath(bar_path,QColor('#646a73'))
            if self.state and self.state.length:
                if self.state.selection:
                    a,b=self.state.selection; x1=max(self.track_left(),self.x_for(a)); x2=min(self.track_right(),self.x_for(b))
                    if x2>x1:
                        area=QRectF(x1,bar.top()-2,x2-x1,bar.height()+4)
                        p.save(); p.setClipPath(bar_path,Qt.ClipOperation.IntersectClip); p.fillRect(area,QColor(104,224,207,75)); p.restore()
                        p.setPen(QPen(ACCENT,1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(area)
                        p.fillRect(QRectF(x1,area.top()-1,2,area.height()+2),ACCENT); p.fillRect(QRectF(x2-2,area.top()-1,2,area.height()+2),ACCENT)
                self.paint_hover_highlight(p,bar_path); self.paint_current_highlight(p,bar_path)
                self.drawing_track.paint_simple(p)
                self.paint_ruler(p,True,bar_path)
                p.setPen(QPen(QColor('#ffffff'),2)); x=self.x_for(self.state.position)
                if self.track_left()<=x<=self.track_right(): p.drawLine(QPointF(x,bar.top()-2),QPointF(x,bar.bottom()+4))
            self.paint_selection_label(p); self.paint_simple_move(p); self.paint_frame_indicator(p); p.end(); return
        p.setFont(QFont('Segoe UI',9)); p.setPen(MUTED)
        p.drawText(QRectF(0,self.track_y('video'),self.track_left(),19),Qt.AlignmentFlag.AlignCenter,tr('VIDÉO'))
        p.drawText(QRectF(0,self.track_y('audio'),self.track_left(),19),Qt.AlignmentFlag.AlignCenter,tr('AUDIO'))
        p.setPen(QColor('#27313e')); p.drawLine(0,38,self.width(),38)
        if not self.state or not self.state.length:
            p.setPen(MUTED); p.drawText(90,85,tr('Votre montage apparaîtra ici.')); p.end(); return
        n=self.state.length
        self.paint_ruler(p,False)
        track_area=QRectF(self.track_left(),38,self.track_width(),self.height()-38)
        p.setClipRect(track_area)
        colors=['#365f63','#36586b']
        left=self.track_left(); scale=self.track_width()/self.span()
        view_end=self.view_start+self.span()
        for track,segments in [('video',self.state.segments),('audio',self.state.audio)]:
            last_pixel=None
            for i,at,seg in self.track_indices[track].visible(segments,self.view_start,view_end):
                x1=left+(at-self.view_start)*scale; x2=x1+seg.length*scale
                if x2-x1<1 and math.floor(x1)==last_pixel: continue
                last_pixel=math.floor(x1); w=max(1,x2-x1-(2 if at+seg.length<n else 0))
                y,h=self.track_y(track),19
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#484c52' if seg.muted else '#080b10' if seg.media is None else colors[i%len(colors)] if track=='video' else '#1e3c38')); p.drawRoundedRect(QRectF(x1,y,w,h),4,4)
                if track=='video' and w>16:
                    p.setPen(QColor('#d5eaf1')); text=self.media.get(seg.media,{}).get('name','N/A')+(tr(' · DÉSACTIVÉ') if seg.muted else '')
                    p.save(); font=QFont('Noto Sans'); font.setPixelSize(12); p.setFont(font)
                    text_left=max(self.track_left(),x1)+5; text_right=min(self.track_right(),x1+w)-5
                    area=QRectF(text_left,y,max(0,text_right-text_left),h)
                    title=p.fontMetrics().elidedText(f'{text} · {seg.length} '+tr('img'),Qt.TextElideMode.ElideRight,int(area.width()))
                    p.setClipRect(area,Qt.ClipOperation.IntersectClip); p.drawText(area,Qt.AlignmentFlag.AlignCenter,title); p.restore()
                elif track=='audio':
                    p.setPen(QPen(QColor('#85888d' if seg.muted else '#65ba9f'),1)); wave=self.wave.get(seg.media)
                    if wave is not None and w>3:
                        full=self.media[seg.media]['frames']
                        for dx in range(max(2,int(self.track_left()-x1)),min(int(w)-1,int(self.track_right()-x1)),3):
                            frame=seg.start+dx/max(1,w)*seg.length; idx=min(len(wave)-1,int(frame/full*len(wave)))
                            amp=max(1,float(wave[idx])*(h/2-2)); p.drawLine(QPointF(x1+dx,y+h/2-amp),QPointF(x1+dx,y+h/2+amp))
                    else: p.drawLine(QPointF(x1+3,y+h/2),QPointF(x1+w-3,y+h/2))
        if self.drop_frame is not None:
            x=self.animated_x if self.animated_x is not None else self.x_for(self.drop_frame); p.setPen(QPen(QColor('#ff963b'),3)); p.drawLine(QPointF(x,40),QPointF(x,self.height()-4))
        if self.state.selection:
            a,b=self.state.selection; x1,x2=self.x_for(a),self.x_for(b)
            p.setPen(QPen(ACCENT,1)); p.setBrush(QColor(104,224,207,35)); p.drawRect(QRectF(x1,42,max(2,x2-x1),54))
            p.setBrush(ACCENT); p.drawRect(QRectF(x1,42,3,54)); p.drawRect(QRectF(max(x1,x2-3),42,3,54))
        if self.state.loop_range:
            a,b=self.state.loop_range
            p.setPen(QPen(QColor('#e9b566'),3)); p.drawLine(QPointF(self.x_for(a),self.height()-4),QPointF(self.x_for(b),self.height()-4))
        x=self.x_for(self.state.position)
        p.setPen(QPen(QColor('#ffffff'),2)); p.drawLine(QPointF(x,34),QPointF(x,self.height()-5))
        p.setBrush(QColor('#ffffff')); p.drawEllipse(QPointF(x,35),4,4)
        self.drawing_track.paint(p)
        if self.move_span and self.ghost_x is not None:
            a,b,track=self.move_span; linked=self.linked or self.gesture=='copy'; top=self.track_y('video' if linked else track); h=45 if linked else 19
            source=QRectF(self.x_for(a),top,max(4,self.x_for(b)-self.x_for(a)),h)
            if self.gesture!='copy': p.fillRect(source,QColor(0,0,0,160))
            p.setPen(QPen(QColor('#8090a0'),1,Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(source)
            width=max(28,self.x_for(b)-self.x_for(a)); gx=max(self.track_left(),min(self.ghost_x,self.track_right()-width))
            p.setPen(QPen(QColor('#ffb35e'),2)); p.setBrush(QColor(215,132,40,215)); p.drawRoundedRect(QRectF(gx,top-7,width,h),5,5)
            p.setPen(QColor('#ffffff')); p.save(); p.setClipRect(QRectF(gx+4,top-7,width-8,h),Qt.ClipOperation.IntersectClip); p.drawText(QRectF(gx+6,top-7,width-12,h),Qt.AlignmentFlag.AlignCenter,tr(('Copie · ' if self.gesture=='copy' else '')+f'{b-a} images · '+('vidéo + audio' if linked else track))); p.restore(); p.setClipRect(track_area)
            p.setPen(QColor('#ffbc70')); text=('Copie' if self.gesture=='copy' else 'Insertion')+f' : image {self.drop_frame}' + (' · vide conservé' if self.leave_gap and self.gesture!='copy' else '')
            p.setClipping(False); p.fillRect(QRectF(self.track_left(),0,300,30),QColor('#161b23')); p.drawText(QRectF(self.track_left()+5,0,320,28),Qt.AlignmentFlag.AlignVCenter,tr(text))
        self.paint_hover_highlight(p); self.paint_current_highlight(p); self.paint_selection_label(p); self.paint_frame_indicator(p); p.end()
    def context_target(self,x,y,use_selection=True):
        if not self.state or not self.state.length: return None
        if getattr(self,'simple',False): track='video'
        elif self.track_y('video')<=y<=self.track_y('video')+19: track='video'
        elif self.track_y('audio')<=y<=self.track_y('audio')+19: track='audio'
        else: return None
        frame=self.frame_for(x)
        if use_selection and self.state.selection and self.state.selection[0]<=frame<self.state.selection[1]:
            return (*self.state.selection,track)
        at=0
        for seg in (self.state.segments if track=='video' else self.state.audio):
            if at<=frame<at+seg.length: return (at,at+seg.length,track)
            at+=seg.length
    def contextMenuEvent(self,event):
        menu=self.context_menu(event.pos()); menu.exec(event.globalPos()); menu.deleteLater()
    def add_timeline_mode(self,menu):
        action=menu.addAction(tr('Timeline simplifiée')); action.setData('timeline_simple'); action.setCheckable(True); action.setChecked(getattr(self,'simple',False))
        action.triggered.connect(lambda checked:self.simpleRequested.emit(checked))
    def add_units(self,menu):
        for title,units in [('Timecode','time'),('Frames','frames')]:
            action=menu.addAction(tr(title)); action.setData('units_'+units); action.setCheckable(True); action.setChecked(self.units==units)
            action.triggered.connect(lambda checked=False,u=units:self.set_units(u))
    def context_menu(self,pos):
        if not self.simple and pos.y()<self.track_y('video') and self.state and self.state.length:
            return self.drawing_track.context_menu(pos.x())
        menu=QMenu(tr(self)); simple=getattr(self,'simple',False)
        self.add_units(menu); menu.addSeparator(); self.add_timeline_mode(menu)
        if not simple and pos.y()<38: self.add_delete_keys(menu,pos.x()); return menu
        menu.addSeparator()
        target=self.context_target(pos.x(),pos.y())
        if target is None: self.add_delete_keys(menu,pos.x()); return menu
        a,b,track=target
        for target_track,title in [('video','Supprimer la vidéo'),('audio','Supprimer l’audio')]:
            action=menu.addAction(tr(title))
            action.triggered.connect(lambda checked=False,t=target_track:self.deleteRequested.emit(a,b,t))
        menu.addSeparator()
        action=menu.addAction(tr('Supprimer le média')); action.triggered.connect(lambda:self.deleteMediaRequested.emit(a,b))
        da,db,dt=self.context_target(pos.x(),pos.y(),False)
        key=locate(self.state.segments,da)[0]
        action=menu.addAction(tr('Changer la cadence…')); action.setEnabled(key is not None and self.media.get(key,{}).get('has_video',True)); action.triggered.connect(lambda:self.cadenceRequested.emit(da,db))
        action=menu.addAction(tr('Dupliquer le média')); action.setEnabled(locate(self.state.audio if dt=='audio' else self.state.segments,da)[0] is not None); action.triggered.connect(lambda:self.duplicated.emit(da,db,-1))
        menu.addSeparator()
        action=menu.addAction(tr('Désactiver / Activer '+('la vidéo' if track=='video' else 'l’audio'))); action.triggered.connect(lambda:self.muteRequested.emit(a,b,track))
        action=menu.addAction(tr('Scinder')); action.triggered.connect(lambda:self.splitRequested.emit(track))
        self.add_delete_keys(menu,pos.x()); return menu
    def add_delete_keys(self,menu,x):
        from drawing import active_key
        self.add_marker_actions(menu,x)
        available=bool(self.state and self.state.length)
        frame=self.frame_for(x) if available else 0; key=active_key(self.state.drawings,frame) if available else None
        selected=self.state.selection if available else None
        span=selected if selected and selected[0]<=frame<selected[1] else (key.start,key.end) if key else (frame,frame+1)
        if menu.actions() and not menu.actions()[-1].isSeparator(): menu.addSeparator()
        action=menu.addAction(tr('Supprimer les clés')); action.setData('delete_keys'); action.setEnabled(available and any(k.start<span[1] and k.end>span[0] for k in self.state.drawings))
        action.triggered.connect(lambda:self.drawingDelete.emit(*span))

    def add_marker_actions(self,menu,x):
        available=bool(self.state and self.state.length)
        frame=min(self.frame_for(x),self.state.length-1) if available else 0; selection=self.state.selection if available else None
        a,b=selection if selection and selection[0]<=frame<selection[1] else (frame,frame+1)
        if menu.actions() and not menu.actions()[-1].isSeparator(): menu.addSeparator()
        action=menu.addAction(tr('Ajouter un marqueur')); action.setData('add_marker'); action.setEnabled(available and frame not in self.state.frame_markers); action.triggered.connect(lambda:self.markerAdded.emit(frame))
        action=menu.addAction(tr('Supprimer les marqueurs')); action.setData('delete_markers'); action.setEnabled(available and any(a<=f<b for f in self.state.frame_markers)); action.triggered.connect(lambda:self.markersDeleted.emit(a,b))

    def boundary_for(self,x):
        frame=max(0,min(self.state.length,round(self.raw_frame(x)))); at=0
        audio=self.move_span and self.move_span[2]=='audio' and not self.linked and self.gesture!='copy'
        for seg in (self.state.audio if audio else self.state.segments):
            end=at+seg.length
            if at<frame<end and seg.media is not None: return at if frame-at<=end-frame else end
            at=end
        return frame
    def begin_range_drag(self,frame):
        self.range_anchor=frame; self.range_frame=frame; self.range_selecting=False; self.range_active=False
    def update_range_drag(self,frame,modifiers):
        if not self.range_active:
            self.range_active=True; self.scrubStarted.emit()
        selecting=bool(modifiers&Qt.KeyboardModifier.ShiftModifier)
        if selecting and not self.range_selecting: self.range_anchor=self.range_frame
        self.range_frame=frame; self.range_selecting=selecting
        if selecting: self.selectionDragged.emit(min(frame,self.range_anchor),max(frame,self.range_anchor)+1,frame)
        else: self.seek.emit(frame)
        return 'select' if selecting else 'scrub'
    def finish_range_drag(self):
        if getattr(self,'range_active',False):
            self.range_active=False; self.scrubFinished.emit()
    def range_key_event(self,e,pressed):
        if e.key()!=Qt.Key.Key_Shift or self.anchor is None or self.gesture not in ('scrub','select'): return False
        if not e.isAutoRepeat():
            modifiers=e.modifiers()|Qt.KeyboardModifier.ShiftModifier if pressed else e.modifiers()&~Qt.KeyboardModifier.ShiftModifier
            self.gesture=self.update_range_drag(self.range_frame,modifiers)
        e.accept(); return True
    def keyPressEvent(self,e):
        if not self.range_key_event(e,True): super().keyPressEvent(e)
    def keyReleaseEvent(self,e):
        if not self.range_key_event(e,False): super().keyReleaseEvent(e)
    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.MiddleButton and e.modifiers()&Qt.KeyboardModifier.ControlModifier:
            self.nav=(e.position().x(),self.view_start); self._timeline_drag=ContinuousDrag(e.globalPosition()); self.drag_scale=self.span()/self.track_width(); e.accept(); return
        if not self.state or not self.state.length or e.button()!=Qt.MouseButton.LeftButton: return
        self.setFocus()
        frame=self.frame_for(e.position().x()); self.anchor=frame; self.drag_frame=self.raw_frame(e.position().x()); self.drag_scale=self.span()/self.track_width(); self._timeline_drag=ContinuousDrag(e.globalPosition())
        if e.modifiers()&Qt.KeyboardModifier.AltModifier and e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
            target=self.context_target(e.position().x(),e.position().y(),False)
            if not target: self.anchor=None; return
            a,b,track=target
            if locate(self.state.audio if track=='audio' else self.state.segments,a)[0] is None: self.anchor=None; return
            self.gesture='copy'; self.copy_origin=e.position(); self.move_span=target; self.grab_offset=e.position().x()-self.x_for(a); self.target_drop(e.position().x())
        elif e.modifiers()&Qt.KeyboardModifier.AltModifier:
            track='audio' if e.position().y()>=self.track_y('audio')-4 else 'video'
            if self.state.selection and self.state.selection[0]<=frame<self.state.selection[1]: span=self.state.selection
            else:
                at=0; span=None
                for seg in (self.state.audio if track=='audio' else self.state.segments):
                    if at<=frame<at+seg.length: span=(at,at+seg.length); break
                    at+=seg.length
            self.gesture='move'; self.move_span=(*span,track); self.grab_offset=e.position().x()-self.x_for(span[0]); self.target_drop(e.position().x())
        else:
            self.begin_range_drag(frame); self.gesture=self.update_range_drag(frame,e.modifiers())
    def mouseMoveEvent(self,e):
        if self.nav:
            self.view_start=self.nav[1]-self._timeline_drag.move(e.globalPosition()).x()*self.drag_scale; self.clamp_view(); self.update(); return
        self.hover_x=e.position().x()
        if self.anchor is None: self.update(); return
        raw=max(0,min(self.state.length,self.drag_frame+self._timeline_drag.move(e.globalPosition()).x()*self.drag_scale))
        frame=min(self.state.length-1,int(raw)); self.ensure_visible(frame)
        if self.gesture in ('select','scrub'): self.gesture=self.update_range_drag(frame,e.modifiers())
        elif self.gesture in ('move','copy'): self.target_drop(self.x_for(raw))
    def mouseReleaseEvent(self,e):
        if hasattr(self,'_timeline_drag'): self._timeline_drag.finish()
        self.nav=None
        if self.gesture in ('move','copy') and self.move_span:
            a,b,track=self.move_span
            if self.gesture=='copy':
                if self._timeline_drag.total.manhattanLength()>=4: self.duplicated.emit(a,b,self.drop_frame)
            else: self.moved.emit(a,b,self.drop_frame,track)
        self.drag_animation.stop(); self.anchor=None; self.gesture=None; self.move_span=None; self.drop_frame=None; self.ghost_x=None; self.animated_x=None; self.update(); self.finish_range_drag()

    def mouseDoubleClickEvent(self,e):
        if e.button()!=Qt.MouseButton.LeftButton or not e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
            return super().mouseDoubleClickEvent(e)
        if not self.track_left()<=e.position().x()<=self.track_left()+self.track_width(): return
        target=self.context_target(e.position().x(),e.position().y(),False)
        if not target: return
        a,b,track=target
        if locate(self.state.audio if track=='audio' else self.state.segments,a)[0] is None: return
        if hasattr(self,'_timeline_drag'): self._timeline_drag.finish()
        self.anchor=None; self.gesture=None; self.selection_track=track
        self.selectionDragged.emit(a,b,self.frame_for(e.position().x()))
        self.finish_range_drag(); self.update(); e.accept()

