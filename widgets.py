# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from ui_text import tr
import math
import numpy as np
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QEvent, QVariantAnimation, QEasingCurve, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QImage, QPainterPath, QPainterPathStroker, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget, QDoubleSpinBox, QSpinBox, QMenu, QPushButton
from media import exposure_lut
from model import locate
from drag import ContinuousDrag
from drawing_timeline import DrawingTimeline
from timeline_drop import ClipDragPreview
from preferences import default_canvas, modifier_name

BG=QColor('#101318'); PANEL=QColor('#191e26'); MUTED=QColor('#8895a7'); TEXT=QColor('#e8edf5'); ACCENT=QColor('#68e0cf')
from studio_transport import TransportButton, VolumeBars

def paint_frame_number(p,frame,center,y,bounds,active=False,compact=False):
    p.save(); p.resetTransform(); p.setClipping(False)
    if compact:
        from timeline_skin import font
        p.setFont(font(10,True))
    else: p.setFont(QFont('Segoe UI',11,QFont.Weight.Bold) if active else QFont('Segoe UI',8))
    text=str(frame); width=p.fontMetrics().horizontalAdvance(text)+10
    height=p.fontMetrics().height()+2
    x=max(bounds.left(),min(center-width/2,bounds.right()-width))
    y=max(bounds.top(),min(y,bounds.bottom()-height))
    area=QRectF(x,y,width,height)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#243a3d' if active else '#24303b') if compact else QColor(12,15,20,205)); p.drawRoundedRect(area,3,3)
    p.setPen(QColor('#a2e9da' if compact else '#ffffff') if active else QColor('#b8c3d1')); p.drawText(area,Qt.AlignmentFlag.AlignCenter,text); p.restore()
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

class Viewer(QWidget):
    presentationChanged=Signal()
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
        from preferences import DEFAULT_SCRUB_PIXELS
        self.scrub_pixels=DEFAULT_SCRUB_PIXELS; self.flip_h=False; self.flip_v=False
        from viewer_cursor import ViewerCursor
        self.cursor_guard=ViewerCursor(self)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        from video_surface import attach_surface
        attach_surface(self)
    def update(self,*args):
        super().update(*args)
        if getattr(self,'surface',None) is not None: self.surface.update()
        self.presentationChanged.emit()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.surface is not None: self.surface.setGeometry(self.rect())
        self.presentationChanged.emit()
    def showEvent(self,event):
        super().showEvent(event)
        self.cursor_guard.activate()
        if self.graphics_startup is not None: self.graphics_startup.schedule()
    def hideEvent(self,event):
        self.cursor_guard.deactivate(); super().hideEvent(event)
    def set_frame(self,arr):
        from composite_media import LayerFrame
        self.layer_frame=arr if isinstance(arr,LayerFrame) else None
        self.rgb=arr.compose() if self.layer_frame is not None else arr
        self.loaded=True; self.apply_effect()
    def set_exposure(self,ev): self.ev=ev; self.apply_effect()
    def apply_effect(self):
        if self.rgb is not None:
            signature=(id(self.rgb),id(self.reference_rgb),self.ev,self.flip_h,self.flip_v,self.comparing,self.compare_mode,self.compare_opacity,self.compare_gain,self.compare_swapped,getattr(self,'geometry_segment',None),getattr(self,'geometry_aspect',None),getattr(self,'geometry_source',False))
            signature+=(getattr(self,'layer_geometry_ids',()),tuple(sorted((getattr(self,'layer_exposures',None) or {}).items())))
            if signature==getattr(self,'_effect_signature',None): return
            from clip_geometry import apply_geometry
            from native_render import rgb_image
            if getattr(self,'layer_frame',None) is not None:
                prepared=self.layer_frame.compose(getattr(self,'layer_geometry_ids',()),getattr(self,'geometry_segment',None),
                    getattr(self,'geometry_source',False),getattr(self,'layer_exposures',None))
            else: prepared=apply_geometry(self.rgb,getattr(self,'geometry_segment',None),getattr(self,'geometry_aspect',None),getattr(self,'geometry_source',False))
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
    def clear(self): self.layer_frame=None; self._effect_signature=None; self._effect_sources=None; self.gpu_packet=None; self._cpu_preview=None; self.reference_rgb=None; self.rgb=None; self.image=None; self.loaded=False; self.update()
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
            p.setPen(MUTED); p.setFont(QFont('Segoe UI',10))
            caption=tr('Double-cliquez pour ouvrir une vidéo et commencer votre montage.')
            available=QRectF(5,cy+30,self.width()-10,self.height()-cy-33)
            flags=Qt.AlignHCenter|Qt.AlignTop|Qt.TextWordWrap
            caption_fits=p.boundingRect(available,flags,caption).height()<=available.height()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(QRectF(cx-42,cy-(55 if caption_fits else 34),84,68),self._welcome_icon)
            if caption_fits:
                p.drawText(available,flags,caption)
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
        handle=getattr(getattr(self,'wipe_interaction',None),'focus_handle',None)
        if handle is not None and handle.hasFocus():
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#ffcf96'),1.6/self.zoom))
            p.drawRoundedRect(QRectF(x-8/self.zoom,-12/self.zoom,16/self.zoom,24/self.zoom),6/self.zoom,6/self.zoom)
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

from track_rows import TrackRows


class Timeline(TrackRows,QWidget):
    mediaTrackSelected=Signal(str,str)
    mediaTrackAdded=Signal()
    mediaTrackRemoved=Signal(str)
    mediaTrackReordered=Signal(str,int)
    mediaAudioExpanded=Signal(str,bool)
    mediaAudioEnabled=Signal(str,bool)
    mediaTransferred=Signal(str,str,int,int,int,bool)
    mediaReferenceRequested=Signal(str)
    cadenceRequested=Signal(int,int)
    scrubStarted=Signal()
    scrubFinished=Signal()
    seek=Signal(int)
    selected=Signal(int,int)
    clipsPicked=Signal(object,str,int)
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
    drawingKeyAdded=Signal()
    renameMarker=Signal(int)
    markerAdded=Signal(int)
    markerMoved=Signal(int,int)
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
        self.clip_preview=ClipDragPreview(self)
        from timeline_thumbnails import ClipThumbnails
        self.thumbnails=ClipThumbnails(self)
        from timeline_gestures import MarkerDrag
        self.marker_drag=MarkerDrag(self)
        self.setMouseTracking(True); self.setToolTip(tr('Glisser : scrub · Maj + glisser : sélectionner · Alt + glisser : déplacer · Alt + Maj + glisser : dupliquer avec le son'))
    def animate_drop(self,value): self.animated_x=float(value); self.update()
    def target_drop(self,x):
        self.snap_drop(self.boundary_for(x),x)
    def snap_drop(self,target,x):
        changed=target!=self.drop_frame
        if changed:
            self.drop_frame=target; end=self.x_for(target)
            self.drag_animation.stop(); self.drag_animation.setStartValue(self.animated_x if self.animated_x is not None else end); self.drag_animation.setEndValue(end); self.drag_animation.start()
        self.ghost_x=x-self.grab_offset
        lifting=self.clip_preview.phase!='lift'
        if lifting: self.clip_preview.lift()
        if changed or lifting: self.clip_preview.describe_target()
        self.update()
    def set_document(self,state,media,fps):
        if self.clip_preview.phase=='land' and (state is not self.state or self.simple!=self._land_simple):
            self.clip_preview.clear()
        if not state or not state.selection or self.state is None or self.state.tracks!=state.tracks:
            self.clip_anchor=None
        self.state=state; self.setFixedHeight(42 if self.simple else self.media_height()); self.media=media; self.fps=float(fps); self.clamp_view(); self.update()
    def set_units(self,units):
        self.units=units; self.update(); self.unitsChanged.emit(units)
    def install_scrub_band(self,band):
        from timeline_gestures import BandScrub
        self.band_scrub=BandScrub(self,band)
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
    def track_y(self,track): return self.media_track_y(track)
    def showEvent(self,event):
        super().showEvent(event)
        host=self.window()
        if host is not self: host.installEventFilter(self)
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.Resize and watched is self.window() and self.state and not self.simple:
            self.setFixedHeight(self.media_height())
        return super().eventFilter(watched,event)
    def track_rect(self,track):
        height=self.video_height(self.active_media)-6 if track=='video' else 19
        return QRectF(self.track_left(),self.track_y(track),self.track_width(),height)
    def simple_track_rect(self): return QRectF(self.track_left(),self.media_top()+1,self.track_width(),17)
    def track_left(self): return min(163 if self.width()>1000 else 139 if self.width()>760 else 126, max(22,self.width()//3))
    def track_right(self):
        margin=40 if self.units=='time' else 32
        return max(self.track_left()+1,self.width()-margin)
    def track_width(self): return max(1,self.track_right()-self.track_left())
    def raw_frame(self,x):
        frame=self.view_start+(x-self.track_left())/self.track_width()*self.span()
        boundary=round(frame)
        return float(boundary) if abs(frame-boundary)<1e-9 else frame
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
        top=self.ruler_y(); bounds=QRectF(self.track_left(),top,self.track_width(),24)
        current_area=None
        if bounds.left()<=x<=bounds.right(): current_area=paint_frame_number(p,self.tick_label(current),x,top+1,bounds,active=True,compact=True)
        indicator=self.frame_indicator()
        if indicator is not None:
            frame,hx=indicator
            text=self.tick_label(frame)
            p.save(); p.setFont(QFont('Segoe UI',8)); width=p.fontMetrics().horizontalAdvance(text)+10; p.restore()
            left=max(bounds.left(),min(hx-width/2,bounds.right()-width))
            area=QRectF(left,top+3,width,21)
            if frame!=current and (current_area is None or not current_area.adjusted(-5,0,5,0).intersects(area)):
                paint_frame_number(p,text,hx,top+3,bounds,compact=True)
    def paint_current_highlight(self,p,bar_path=None):
        if not self.state or not self.state.length: return
        frame=max(0,min(self.state.position,self.state.length-1))
        left=self.track_left(); right=left+self.track_width(); x=self.x_for(frame)
        if not left<=x<=right: return
        width=max(3,self.x_for(frame+1)-x)
        bar=self.simple_track_rect()
        y,h=(bar.top(),bar.height()) if self.simple else (self.media_top(),self.height()-self.media_top())
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
        y,h=(bar.top(),bar.height()) if self.simple else (self.media_top(),max(1,self.height()-self.media_top()))
        p.save(); p.setClipRect(QRectF(left,y,right-left,h))
        if bar_path is not None: p.setClipPath(bar_path,Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(x1,y,x2-x1,h),QColor(218,249,245,76)); p.restore()
    def leaveEvent(self,event):
        self.hover_marker=None; self.hover_point=None; self.drawing_track.hover_handle=None
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
    def selection_label(self):
        if not self.state or not self.state.selection: return ''
        from studio_chrome import frame_clock
        length=sum(b-a for a,b in self.state.selection_ranges())
        unit=tr('image') if length==1 else tr('images')
        return f'{length} {unit} · {frame_clock(length,self.fps)}'
    def paint_selection_label(self,p):
        if not self.state or not self.state.selection: return
        from timeline_skin import font, label
        right=min(self.track_left(),getattr(self,'ruler_text_left',self.track_left()))
        area=QRectF(4,self.ruler_y()+1,right-8,self.ruler_height()-2)
        p.save(); p.setPen(Qt.NoPen); p.setBrush(QColor('#244548')); p.drawRoundedRect(area,3,3)
        p.setFont(font(11,True))
        text=self.selection_label()
        if p.fontMetrics().horizontalAdvance(text)<=area.width()-6:
            label(p,area,text,'#adfff2',11,True,align=Qt.AlignCenter)
        else:
            count, duration=text.split(' · ')
            label(p,QRectF(area.x(),area.y(),area.width(),12),count,'#adfff2',10,True,True,Qt.AlignCenter)
            label(p,QRectF(area.x(),area.y()+12,area.width(),12),duration,'#d1ece8',10,True,align=Qt.AlignCenter)
        p.restore()
    def media_boundaries(self):
        if not self.state: return []
        positions=[]; last=None
        for _,at,segment in self.track_indices['video'].visible(self.active_media.segments,self.view_start,self.view_start+self.span()):
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
    def paintEvent(self,e):
        from timeline_skin import paint
        painter=QPainter(self)
        try:
            paint(self,painter)
        finally:
            painter.end()
    def context_target(self,x,y,use_selection=True):
        self.activate_media_row(y)
        if not self.state or not self.state.length: return None
        if getattr(self,'simple',False): track='video'
        elif self.track_y('video')-3<=y<self.track_y('audio')-3: track='video'
        elif self.active_media.info.audio_expanded and self.track_y('audio')-3<=y<self.track_y('audio')+19: track='audio'
        else: return None
        frame=self.frame_for(x)
        if use_selection and self.state.selection and self.state.selection[0]<=frame<self.state.selection[1]:
            return (*self.state.selection,track)
        at=0
        for seg in (self.active_media.segments if track=='video' else self.active_media.audio):
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
        from timeline_skin import marker_at
        menu=self.timeline_context_menu(pos)
        marker=marker_at(self,pos)
        if marker:
            from PySide6.QtGui import QAction
            action=QAction(tr('Renommer le marqueur…'),menu)
            action.setData('rename_marker')
            action.triggered.connect(lambda checked=False:self.renameMarker.emit(marker[0]))
            first=next(iter(menu.actions()),None)
            menu.insertAction(first,action)
            menu.insertSeparator(first)
        return menu
    def timeline_context_menu(self,pos):
        header=self.media_header_menu(pos)
        if header is not None: return header
        if (self.drawing_track.contains(pos) or not self.simple and pos.y()<self.media_top()) and self.state and self.state.length:
            return self.drawing_track.context_menu(pos.x())
        menu=QMenu(tr(self)); simple=getattr(self,'simple',False)
        self.add_units(menu); menu.addSeparator(); self.add_timeline_mode(menu)
        if not simple and pos.y()<38: self.add_delete_keys(menu,pos.x()); return menu
        menu.addSeparator()
        target=self.context_target(pos.x(),pos.y())
        if target is None: self.add_delete_keys(menu,pos.x()); return menu
        a,b,track=target
        self.add_media_audio_action(menu,self.active_media)
        menu.addSeparator()
        for target_track,title in [('video','Supprimer la vidéo'),('audio','Supprimer l’audio')]:
            action=menu.addAction(tr(title))
            action.triggered.connect(lambda checked=False,t=target_track:self.deleteRequested.emit(a,b,t))
        menu.addSeparator()
        action=menu.addAction(tr('Supprimer le média')); action.triggered.connect(lambda:self.deleteMediaRequested.emit(a,b))
        da,db,dt=self.context_target(pos.x(),pos.y(),False)
        key=locate(self.active_media.segments,da)[0]
        action=menu.addAction(tr('Changer la cadence…')); action.setEnabled(key is not None and self.media.get(key,{}).get('has_video',True)); action.triggered.connect(lambda:self.cadenceRequested.emit(da,db))
        action=menu.addAction(tr('Dupliquer le média')); action.setEnabled(locate(self.active_media.audio if dt=='audio' else self.active_media.segments,da)[0] is not None); action.triggered.connect(lambda:self.duplicated.emit(da,db,-1))
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
        for seg in (self.active_media.audio if audio else self.active_media.segments):
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
        if e.key()==Qt.Key.Key_Escape and self.gesture in ('move','copy','transfer'):
            self.cancel_clip_drag(); e.accept(); return
        if not self.range_key_event(e,True): super().keyPressEvent(e)
    def event(self,e):
        if e.type()==QEvent.Type.ToolTip:
            from html import escape
            from PySide6.QtWidgets import QToolTip
            from timeline_skin import marker_at
            marker=marker_at(self,e.pos())
            if marker:
                text=escape(' · '.join(filter(None,(marker[1],self.tick_label(marker[0])))))
                QToolTip.showText(e.globalPos(),'<span>'+text+'</span>',self)
                return True
        if getattr(self,'gesture',None) in ('move','copy','transfer'):
            if e.type()==QEvent.Type.ShortcutOverride and e.key()==Qt.Key.Key_Escape:
                e.accept(); return True
            if e.type() in (QEvent.Type.WindowDeactivate,QEvent.Type.Hide,QEvent.Type.FocusOut):
                self.cancel_clip_drag()
        return super().event(e)
    def cancel_clip_drag(self):
        self._timeline_drag.finish()
        self.clear_clip_drag()
    def clear_clip_drag(self):
        self.cross_origin=None; self.cross_target=None; self.anchor=None; self.gesture=None
        self.move_span=None; self.drop_frame=None; self.ghost_x=None; self.animated_x=None
        self.drag_animation.stop(); self.clip_preview.clear(); self.finish_range_drag()
    def keyReleaseEvent(self,e):
        if not self.range_key_event(e,False): super().keyReleaseEvent(e)
    def mousePressEvent(self,e):
        self._ctrl_snapshot=None
        if e.button()==Qt.LeftButton and self.state and e.modifiers() in (Qt.ControlModifier,Qt.ControlModifier|Qt.ShiftModifier):
            self._ctrl_snapshot=(e.position(),e.modifiers(),self.selected_clip_spans())
            if e.modifiers()&Qt.ShiftModifier and (self.simple_track_rect().contains(e.position()) if self.simple else self.media_row_at(e.position().y()) is not None):
                e.accept(); return
        if self.toggle_media_selection(e): return
        if self.press_media_title(e): return
        self.activate_media_row(e.position().y())
        if e.button()==Qt.MouseButton.MiddleButton and e.modifiers()&Qt.KeyboardModifier.ControlModifier:
            self.nav=(e.position().x(),self.view_start); self._timeline_drag=ContinuousDrag(e.globalPosition()); self.drag_scale=self.span()/self.track_width(); e.accept(); return
        if not self.state or not self.state.length or e.button()!=Qt.MouseButton.LeftButton: return
        self.setFocus()
        frame=self.frame_for(e.position().x()); self.anchor=frame; self.drag_frame=self.raw_frame(e.position().x()); self.drag_scale=self.span()/self.track_width(); self._timeline_drag=ContinuousDrag(e.globalPosition())
        self.begin_cross_drag(e)
        if e.modifiers()&Qt.KeyboardModifier.AltModifier and e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
            target=self.context_target(e.position().x(),e.position().y(),False)
            if not target: self.anchor=None; return
            a,b,track=target
            if locate(self.active_media.audio if track=='audio' else self.active_media.segments,a)[0] is None: self.anchor=None; return
            self.gesture='copy'; self.copy_origin=e.position(); self.move_span=target; self.grab_offset=e.position().x()-self.x_for(a); self.target_drop(e.position().x())
        elif e.modifiers()&Qt.KeyboardModifier.AltModifier:
            track='audio' if not self.simple and self.active_media.info.audio_expanded and e.position().y()>=self.track_y('audio')-4 else 'video'
            if self.state.selection and self.state.selection[0]<=frame<self.state.selection[1]: span=self.state.selection
            else:
                at=0; span=None
                for seg in (self.active_media.audio if track=='audio' else self.active_media.segments):
                    if at<=frame<at+seg.length: span=(at,at+seg.length); break
                    at+=seg.length
            if span is None: self.anchor=None; return
            self.gesture='move'; self.move_span=(*span,track); self.grab_offset=e.position().x()-self.x_for(span[0]); self.target_drop(e.position().x())
        else:
            self.begin_range_drag(frame); self.gesture=self.update_range_drag(frame,e.modifiers())
    def mouseMoveEvent(self,e):
        if getattr(self,'media_title_drag',None) is not None: return
        if self.nav:
            self.view_start=self.nav[1]-self._timeline_drag.move(e.globalPosition()).x()*self.drag_scale; self.clamp_view(); self.update(); return
        from timeline_skin import marker_at
        self.hover_point=e.position()
        marker=marker_at(self,e.position())
        self.hover_marker=marker[0] if marker else None
        if marker: self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover_x=e.position().x()
        if self.anchor is None: self.update(); return
        raw=max(0,min(self.state.length,self.drag_frame+self._timeline_drag.move(e.globalPosition()).x()*self.drag_scale))
        frame=min(self.state.length-1,int(raw)); self.ensure_visible(frame)
        if self.update_cross_drag(e,self.x_for(raw)): return
        if self.gesture in ('select','scrub'): self.gesture=self.update_range_drag(frame,e.modifiers())
        elif self.gesture in ('move','copy'): self.target_drop(self.x_for(raw))
    def mouseReleaseEvent(self,e):
        if e.button() not in (Qt.MouseButton.LeftButton,Qt.MouseButton.MiddleButton): return
        if self.release_media_title(e): return
        drag=getattr(self,'_timeline_drag',None)
        if getattr(self,'cross_origin',None) and not e.modifiers() & Qt.AltModifier:
            if drag: drag.finish()
            self.clear_clip_drag()
            return
        if (drag and getattr(self,'cross_origin',None) and self.gesture in ('scrub','move','copy','transfer')
                and drag.last!=e.globalPosition()):
            self.mouseMoveEvent(e)
        if drag: drag.finish()
        self.nav=None
        span=self.move_span
        dropping=(self.gesture in ('move','copy','transfer') and span and
                  (self.gesture=='transfer' and self.cross_target or drag and drag.total.manhattanLength()>=4))
        if not dropping:
            if self.gesture is not None: self.clear_clip_drag()
            return
        original=self.state; release_rect=self.clip_preview.current_rect()
        target=getattr(self,'cross_target',None) or self.active_media.info.id
        if self.gesture=='transfer' and self.cross_target and self.cross_origin:
            source,a,b=self.cross_origin
            self.mediaTransferred.emit(source,self.cross_target,a,b,self.drop_frame,self.cross_copy)
        elif self.gesture in ('move','copy') and self.move_span:
            a,b,track=self.move_span
            if self.gesture=='copy':
                self.duplicated.emit(a,b,self.drop_frame)
            else: self.moved.emit(a,b,self.drop_frame,track)
        self.clear_clip_drag()
        if self.state is not original:
            self._land_simple=self.simple
            self.clip_preview.land(release_rect,self.state.position,target)

    def mouseDoubleClickEvent(self,e):
        modifier=e.modifiers()
        if e.button()!=Qt.MouseButton.LeftButton or modifier not in (Qt.NoModifier,Qt.ShiftModifier,Qt.ControlModifier,Qt.ControlModifier|Qt.ShiftModifier):
            return super().mouseDoubleClickEvent(e)
        self.clip_click(e,modifier)

    def selected_clip_spans(self):
        if not self.state or not self.state.selection: return ()
        if self.state.selected_clips: return self.state.selected_clips
        identities=getattr(self,'selected_media_ids',(self.active_media.info.id,))
        return tuple((identity,*self.state.selection) for identity in identities)

    def clip_click(self,e,modifier):
        if self.simple:
            on_strip=self.simple_track_rect().contains(e.position())
            on_title=e.position().x()<self.track_left() and self.media_top()<=e.position().y()<self.height()
            if not on_strip and not (on_title and modifier==Qt.ShiftModifier): return
            media=self.active_media; track='video'
        else:
            media=self.media_row_at(e.position().y())
            if media is None: return
            top=next(y for row,y,height in self.media_rows() if row.info.id==media.info.id)
            track='audio' if media.info.audio_expanded and e.position().y()>=top-3+self.video_height(media) else 'video'
            if e.position().x()<self.track_left() and modifier==Qt.NoModifier:
                if 23<=e.position().x()<self.track_left()-30:
                    self.mediaAudioExpanded.emit(media.info.id,not media.info.audio_expanded)
                self.media_title_drag=None; e.accept(); return
        if not media.length: return
        frame=self.raw_frame(e.position().x())
        a,b=0,media.length
        if modifier!=Qt.ShiftModifier:
            if not self.simple and e.position().x()<self.track_left(): return
            at=0
            for segment in (media.audio if track=='audio' else media.segments):
                end=at+segment.length
                if at<=frame<end and segment.media is not None:
                    a,b=at,end; break
                at=end
            else:
                e.accept(); return
        key=(media.info.id,a,b)
        spans=self.selected_clip_spans()
        snapshot=getattr(self,'_ctrl_snapshot',None)
        self._ctrl_snapshot=None
        if snapshot and snapshot[1]==modifier and (snapshot[0]-e.position()).manhattanLength()<=QApplication.startDragDistance():
            spans=snapshot[2]
        ranges=list(spans) if modifier&Qt.ControlModifier else []
        anchor=getattr(self,'clip_anchor',None)
        if modifier==Qt.ControlModifier:
            spans=sorted((left,right) for identity,left,right in ranges if identity==media.info.id)
            covered=a
            for left,right in spans:
                if left>covered: break
                covered=max(covered,right)
            remaining=[]
            for identity,left,right in ranges:
                if identity!=media.info.id or right<=a or b<=left:
                    remaining.append((identity,left,right))
                else:
                    if left<a: remaining.append((identity,left,a))
                    if b<right: remaining.append((identity,b,right))
            ranges=remaining
            if covered<b:
                ranges.append(key)
                self.clip_anchor=(media.info.id,track,a)
            elif anchor==(media.info.id,track,a): self.clip_anchor=None
        elif modifier==(Qt.ControlModifier|Qt.ShiftModifier):
            if anchor and anchor[:2]==(media.info.id,track):
                origin=anchor[2]
            else:
                origin=next((start for identity,start,end in ranges if identity==media.info.id),self.state.position)
                self.clip_anchor=(media.info.id,track,origin)
            left,right=min(origin,a),max(origin+1,b)
            at=0
            for segment in (media.audio if track=='audio' else media.segments):
                end=at+segment.length
                if at>=right: break
                if end>left and segment.media is not None: ranges.append((media.info.id,at,end))
                at=end
            merged=[]
            for identity,start,end in sorted(set(ranges)):
                if merged and merged[-1][0]==identity and start<merged[-1][2]:
                    merged[-1]=(identity,merged[-1][1],max(end,merged[-1][2]))
                else: merged.append((identity,start,end))
            ranges=merged
        else:
            ranges.append(key)
            self.clip_anchor=None if modifier==Qt.ShiftModifier else (media.info.id,track,a)
        if hasattr(self,'_timeline_drag'): self._timeline_drag.finish()
        self.media_title_drag=None; self.anchor=None; self.gesture=None; self.selection_track=track
        self.cross_origin=None; self.cross_target=None; self.move_span=None
        self.clipsPicked.emit(tuple(ranges),media.info.id,min(b-1,max(a,int(frame))))
        self.finish_range_drag(); self.update(); e.accept()
        return True

