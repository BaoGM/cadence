# SPDX-License-Identifier: GPL-3.0-only
"""Clip geometry: shared crop/placement calculations, preview and export."""
import math
from dataclasses import replace
from PySide6.QtCore import QObject,QEvent,Qt,QRectF,QPointF,QSize
from PySide6.QtGui import QImage, QPainter, QPen, QColor
import numpy as np

IDENTITY=(0.,0.,1.,1.)
def rect_pixels(rect,width,height):
    x,y,w,h=rect
    return round(x*width),round(y*height),max(2,round(w*width)),max(2,round(h*height))
def geometry_filter(seg,width,height):
    x,y,cw,ch=rect_pixels(seg.crop,width,height); cw=min(cw,width-x); ch=min(ch,height-y)
    dx,dy,dw,dh=rect_pixels(seg.placement,width,height)
    if seg.rotation:
        cx,cy=dx+dw/2,dy+dh/2
        extent=max(abs(cx),abs(width-cx),abs(cy),abs(height-cy),math.hypot(dw,dh)/2)+4
        side=2*math.ceil(extent)
        return f'format=rgb24,crop={cw}:{ch}:{x}:{y}:exact=1,scale={dw}:{dh}:force_original_aspect_ratio=decrease,pad={dw}:{dh}:(ow-iw)/2:(oh-ih)/2:black,pad={side}:{side}:(ow-iw)/2:(oh-ih)/2:black,rotate={math.radians(seg.rotation)}:ow=iw:oh=ih:c=black,crop={width}:{height}:{round(side/2-cx)}:{round(side/2-cy)}:exact=1,setsar=1'
    pw=max(width+max(-dx,0),dw+max(dx,0)); ph=max(height+max(-dy,0),dh+max(dy,0))
    return f'format=rgb24,crop={cw}:{ch}:{x}:{y}:exact=1,scale={dw}:{dh}:force_original_aspect_ratio=decrease,pad={dw}:{dh}:(ow-iw)/2:(oh-ih)/2:black,pad={pw}:{ph}:{max(dx,0)}:{max(dy,0)}:black,crop={width}:{height}:{max(-dx,0)}:{max(-dy,0)}:exact=1,setsar=1'
def apply_geometry(rgb,seg,aspect=None,show_source=False):
    if seg is None: return rgb
    h,w=rgb.shape[:2]
    if seg.crop==IDENTITY and seg.placement==IDENTITY and not seg.rotation and (not aspect or abs(w/h-aspect)<.005): return rgb
    if aspect: w=max(2,round(h*aspect))
    # Decoder rows can contain alignment padding; Qt's buffer bridge requires
    # contiguous memory even when a bytes-per-line stride is supplied.
    rgb=np.ascontiguousarray(rgb)
    src=QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888).copy()
    base=QImage(w,h,QImage.Format.Format_RGB888); base.fill(Qt.GlobalColor.black)
    fit=src.size().scaled(QSize(w,h),Qt.AspectRatioMode.KeepAspectRatio)
    p=QPainter(base); p.drawImage(QRectF((w-fit.width())/2,(h-fit.height())/2,fit.width(),fit.height()),src); p.end()
    if show_source: return np.frombuffer(base.bits(),np.uint8).reshape(h,base.bytesPerLine())[:,:w*3].reshape(h,w,3).copy()
    x,y,cw,ch=rect_pixels(seg.crop,w,h); cropped=base.copy(x,y,min(cw,w-x),min(ch,h-y))
    out=QImage(w,h,QImage.Format.Format_RGB888); out.fill(Qt.GlobalColor.black)
    p=QPainter(out); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    dx,dy,dw,dh=rect_pixels(seg.placement,w,h)
    fit=cropped.size().scaled(QSize(dw,dh),Qt.AspectRatioMode.KeepAspectRatio)
    p.translate(dx+dw/2,dy+dh/2); p.rotate(seg.rotation)
    p.drawImage(QRectF(-fit.width()/2,-fit.height()/2,fit.width(),fit.height()),cropped); p.end()
    return np.frombuffer(out.bits(),np.uint8).reshape(h,out.bytesPerLine())[:,:w*3].reshape(h,w,3).copy()

class GeometryTools(QObject):
    def __init__(self,w):
        super().__init__(w); self.w=w; self.v=w.viewer; self.mode=None; self.drag=None; self.pending=None; self.target='clip'
        self.v.geometry_tools=self; self.v.installEventFilter(self); self.v.setMouseTracking(True)
        w.drawing.enabledChanged.connect(lambda checked:self.cancel() if self.mode else None)
    @property
    def rect(self): return self.frame.rect
    @rect.setter
    def rect(self,value): self.frame.rect=QRectF(value)
    def current(self):
        at=0
        for i,s in enumerate(self.w.doc.state.segments):
            if at<=min(self.w.doc.state.position,self.w.doc.state.length-1)<at+s.length: return i,s
            at+=s.length
        return None,None
    def sync(self):
        from drawing import active_key
        i,seg=self.current(); st=self.w.doc.state
        if self.mode:
            invalid=(st.drawings is not self.source or active_key(st.drawings,st.position) is not self.key) if self.target=='drawing' else (st.segments is not self.source or i!=self.index)
            if invalid: self.cancel()
        self.v.geometry_segment=self.pending if self.mode=='resize' and self.target=='clip' else seg
        self.v.geometry_source=self.mode=='crop'
        first=next((self.w.doc.media[s.media] for s in st.segments if s.media and not s.muted),None)
        self.v.geometry_aspect=first['width']/first['height'] if first else None
        self.v.apply_effect()
    def activate(self,mode):
        from drawing import active_key,move_erased_selection
        from transform_frame import TransformFrame
        if self.w.job or self.v.image is None: return
        d=self.w.drawing; d.selection.sync(); selected=d.selection.indices
        key=active_key(self.w.doc.state.drawings,self.w.doc.state.position)
        bounds=d.selection.bounds(key) if selected and key else QRectF()
        if hasattr(self.w,'workspaces') and self.w.workspaces.mode=='read': self.w.workspaces.switch('edit')
        self.cancel(); self.w.pause(); self.w.commit_exposure(); self.w.compare_enabled.setChecked(False)
        aspect=self.v.image.width()/self.v.image.height()
        if mode=='resize' and selected and key and not bounds.isEmpty():
            self.target='drawing'; self.key=key; self.source=self.w.doc.state.drawings
            self.original_indices=selected
            self.base_marks,self.indices=move_erased_selection(key.marks,selected,0,0)
            self.original_rect=QRectF(bounds); self.original_angle=0.; self.frame=TransformFrame(bounds,aspect,centered=len(selected)>1)
            self.pending=key; d.visible.setChecked(True)
        else:
            i,seg=self.current()
            if seg is None or seg.media is None: return
            d.choose_tool('cursor'); self.target='clip'; self.index=i; self.source=self.w.doc.state.segments; self.original=seg; self.pending=seg
            self.original_rect=QRectF(*(seg.crop if mode=='crop' else seg.placement)); self.original_angle=0 if mode=='crop' else seg.rotation
            self.frame=TransformFrame(self.original_rect,aspect,self.original_angle)
        self.mode=mode; self.v.setFocus(); self.sync(); self.v.update()
    def cancel(self):
        if self.mode and self.target=='drawing': self.w.drawing.selection.preview=None; self.w.drawing.invalidate()
        self.mode=None; self.drag=None; self.pending=None
        if hasattr(self.v,'geometry_segment'):
            self.v.geometry_segment=self.current()[1]; self.v.geometry_source=False; self.v.apply_effect()
        self.v.setCursor(Qt.CursorShape.CrossCursor if self.w.drawing.enabled else Qt.CursorShape.OpenHandCursor)
    def commit(self):
        if not self.mode: return
        if self.target=='drawing':
            pending=self.pending; indices=self.original_indices if pending is self.key else self.indices; self.mode=None; self.drag=None; self.w.drawing.selection.preview=None
            self.w.drawing.commit_key(pending,'Transformer les dessins')
            selection=self.w.drawing.selection; selection.indices=indices; selection.source=self.w.doc.state.drawings; selection.key_start=pending.start
            self.w.drawing.invalidate()
        else:
            segs=list(self.source); segs[self.index]=self.pending; label='Recadrer le clip' if self.mode=='crop' else 'Transformer le clip'
            self.mode=None; self.drag=None; self.w.doc.commit(label,replace(self.w.doc.state,segments=tuple(segs)))
            self.w.refresh(); self.w.request_frame()
        self.v.setCursor(Qt.CursorShape.CrossCursor if self.w.drawing.enabled else Qt.CursorShape.OpenHandCursor)
    def reset(self):
        i,seg=self.current()
        if seg is None: return
        self.cancel(); seq=list(self.w.doc.state.segments); seq[i]=replace(seg,crop=IDENTITY,placement=IDENTITY,rotation=0)
        self.w.doc.commit('Réinitialiser le cadrage du clip',replace(self.w.doc.state,segments=tuple(seq))); self.w.refresh(); self.w.request_frame()
    def point(self,pos): return self.w.drawing.point(pos,True)
    def handles(self): return self.frame.handles()
    def hit(self,point):
        size=self.v.image_size().scaled(self.v.size(),Qt.AspectRatioMode.KeepAspectRatio); area=self.w.drawing.a_rect(size)
        return self.frame.hit(point,area.width()*self.v.zoom,area.height()*self.v.zoom,self.mode!='crop')
    def update_pending(self):
        from affine import compose,valid
        if self.target=='drawing':
            matrix=self.frame.delta(self.original_rect,self.original_angle)
            marks=tuple(replace(m,transform=compose(matrix,m.transform)) if i in self.indices else m for i,m in enumerate(self.base_marks))
            if not all(valid(m.transform) for m in marks): return
            self.pending=replace(self.key,marks=marks); self.w.drawing.selection.preview=self.pending; self.w.drawing.invalidate()
        else:
            r=self.rect
            if self.mode=='crop':
                if self.frame.drag and (self.frame.drag['kind']=='move' or self.frame.drag['mods']&Qt.KeyboardModifier.AltModifier):
                    r.moveLeft(max(0,min(1-r.width(),r.left()))); r.moveTop(max(0,min(1-r.height(),r.top())))
                r=r.intersected(QRectF(0,0,1,1))
            else: r=QRectF(max(-3,min(3,r.x())),max(-3,min(3,r.y())),min(4,r.width()),min(4,r.height()))
            if r.width()<.002 or r.height()<.002: return
            self.rect=r; self.pending=replace(self.original,**({'crop':r.getRect()} if self.mode=='crop' else {'placement':r.getRect(),'rotation':self.frame.angle}))
            self.sync()
        self.v.update()
    def eventFilter(self,obj,e):
        if not self.mode or not self.v.loaded: return False
        kind=e.type()
        if kind==QEvent.Type.KeyPress:
            if e.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter): self.commit(); return True
            if e.key()==Qt.Key.Key_Escape: self.cancel(); return True
        if kind in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease) and e.key() in (Qt.Key.Key_Alt,Qt.Key.Key_Control,Qt.Key.Key_Shift): e.accept(); return True
        if kind==QEvent.Type.MouseButtonDblClick and e.button()==Qt.MouseButton.LeftButton: return True
        if kind==QEvent.Type.MouseButtonPress and e.button()==Qt.MouseButton.LeftButton:
            xy=self.point(e.position())
            if xy is None: return True
            point=QPointF(*xy); hit='move' if e.modifiers()&Qt.KeyboardModifier.AltModifier else self.hit(point)
            if hit is None and self.mode=='crop': hit='new'
            if hit is not None: self.frame.begin(hit,point,e.modifiers()); self.drag=True
            return True
        if kind==QEvent.Type.MouseMove:
            xy=self.point(e.position())
            if xy is None: return True
            point=QPointF(*xy)
            if self.drag: self.frame.update(point,e.modifiers()); self.update_pending()
            else:
                hit=self.hit(point)
                cursor=Qt.CursorShape.SizeAllCursor if hit=='move' else Qt.CursorShape.CrossCursor if hit=='rotate' else Qt.CursorShape.SizeFDiagCursor if hit in (0,4) else Qt.CursorShape.SizeBDiagCursor if hit in (2,6) else Qt.CursorShape.SizeVerCursor if hit in (1,5) else Qt.CursorShape.SizeHorCursor if hit in (3,7) else Qt.CursorShape.ArrowCursor
                self.v.setCursor(cursor)
                if hit=='rotate':
                    from transform_frame import rotation_cursor
                    self.v.setCursor(rotation_cursor())
            return True
        if kind==QEvent.Type.MouseButtonRelease and e.button()==Qt.MouseButton.LeftButton: self.drag=None; self.frame.drag=None; return True
        return False
    def paint(self,p,size):
        if not self.mode: return
        from PySide6.QtGui import QPainterPath
        area=self.w.drawing.a_rect(size); transform=self.w.drawing.selection.display_transform(area)
        outline=QPainterPath(); outline.addRect(self.rect); mapped=transform.map(self.frame.matrix().map(outline)); p.save()
        if self.mode=='crop':
            mask=QPainterPath(); mask.addRect(area); p.fillPath(mask.subtracted(mapped),QColor(0,0,0,150))
        pen=QPen(QColor('#68e0cf'),1.5); pen.setCosmetic(True); p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(mapped)
        p.setBrush(QColor('#ffffff')); radius=4/self.v.zoom
        for point in self.handles():
            q=transform.map(point); p.drawRect(QRectF(q.x()-radius,q.y()-radius,2*radius,2*radius))
        q=transform.map(self.rect.center()); p.drawLine(q-QPointF(radius,0),q+QPointF(radius,0)); p.drawLine(q-QPointF(0,radius),q+QPointF(0,radius)); p.restore()
