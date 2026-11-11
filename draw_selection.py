# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QTransform, QPen, QColor
from drawing import active_key,mark_points,move_erased_selection,vector_path,VECTOR_TOOLS
from draw_text import text_bounds
from shape_gesture import ShapeGesture
from affine import qt,IDENTITY

class DrawSelection:
    def __init__(self,controller):
        self.c=controller; self.indices=(); self.source=None; self.key_start=None; self.gesture=None; self.path=None; self.preview=None
    def clear(self): self.indices=(); self.source=None; self.key_start=None; self.gesture=None; self.path=None; self.preview=None
    def sync(self):
        st=self.c.win.doc.state
        if self.source is not st.drawings or active_key(st.drawings,st.position) is not active_key(st.drawings,self.key_start if self.key_start is not None else -1): self.clear()
    def geometry(self,mark):
        v=self.c.viewer; width,height=v.rgb.shape[1],v.rgb.shape[0]; path=QPainterPath()
        if mark.children:
            for child in mark.children:
                if child.tool!='eraser': path=path.united(self.geometry(child))
            return qt(mark.transform).map(path)
        x,y,_=mark.points[0]
        if mark.tool=='text':
            path.addRect(text_bounds(mark,width,height))
        elif mark.tool in VECTOR_TOOLS:
            path=vector_path(mark,width,height); stroker=QPainterPathStroker(); stroker.setWidth(max(2,mark.size*height)); stroker.setCapStyle(Qt.PenCapStyle.RoundCap); path=stroker.createStroke(path)
        else:
            path.moveTo(x*width,y*height)
            for x,y,_ in mark.points[1:]: path.lineTo(x*width,y*height)
            size=max(2,mark.size*height); stroker=QPainterPathStroker(); stroker.setWidth(size); stroker.setCapStyle(Qt.PenCapStyle.RoundCap); path=stroker.createStroke(path)
            x,y,_=mark.points[0]; path.addEllipse(QPointF(x*width,y*height),size/2,size/2)
        return qt(mark.transform).map(QTransform.fromScale(1/width,1/height).map(path))
    def bounds(self,key=None):
        key=key or active_key(self.c.win.doc.state.drawings,self.c.win.doc.state.position)
        result=QRectF()
        if key:
            for i in (getattr(self,'preview_indices',self.indices) if key is self.preview and self.gesture=='translate' else self.indices):
                if i<len(key.marks): result=result.united(self.geometry(key.marks[i]).boundingRect())
        return result
    def begin(self,point,tool,force_move=False):
        self.sync(); st=self.c.win.doc.state; key=active_key(st.drawings,st.position); pos=QPointF(*point)
        if tool=='text':
            if key and len(self.indices)==1 and not force_move:
                index=self.indices[0]; mark=key.marks[index]
                if mark.tool=='text' and mark.transform==IDENTITY:
                    bounds=self.geometry(mark).boundingRect(); v=self.c.viewer; size=v.image.size().scaled(v.size(),Qt.AspectRatioMode.KeepAspectRatio); area=self.c.a_rect(size)
                    corners=(bounds.topLeft(),bounds.topRight(),bounds.bottomRight(),bounds.bottomLeft())
                    for i,corner in enumerate(corners):
                        if abs(pos.x()-corner.x())*area.width()*v.zoom<=8 and abs(pos.y()-corner.y())*area.height()*v.zoom<=8:
                            self.gesture='resize_text'; self.opposite=corners[(i+2)%4]; self.key=key; self.key_start=key.start; self.source=st.drawings; self.preview=key
                            width,height=v.rgb.shape[1],v.rgb.shape[0]
                            self.text_shape=ShapeGesture('rectangle',(self.opposite.x()*width,self.opposite.y()*height),(corner.x()*width,corner.y()*height),(point[0]*width,point[1]*height)); return True
            hits=[i for i,m in enumerate(key.marks) if m.tool=='text' and self.geometry(m).contains(pos)] if key else []
            if not hits: self.clear(); return False
            self.indices=(hits[-1],)
        elif tool=='lasso':
            if not key: self.clear(); return True
            if not self.indices or not self.bounds(key).adjusted(-.006,-.006,.006,.006).contains(pos):
                self.indices=(); self.path=QPainterPath(pos); self.gesture='lasso'; self.source=st.drawings; self.key_start=key.start; self.key=key; return True
        else: self.clear(); return False
        self.anchor=point; self.key=key; self.key_start=key.start; self.source=st.drawings; self.gesture='translate'; self.preview=key; return True
    def move(self,point,alt=False):
        if self.gesture=='lasso': self.path.lineTo(QPointF(*point))
        elif self.gesture=='resize_text':
            width,height=self.c.viewer.rgb.shape[1],self.c.viewer.rgb.shape[0]
            self.text_shape.update((point[0]*width,point[1]*height),alt=alt)
            a,b=self.text_shape.normalized(width,height); x,y=a[:2]; ox,oy=b[:2]; index=self.indices[0]; mark=self.key.marks[index]
            left,top=min(x,ox),min(y,oy); width,height=max(.005,abs(x-ox)),max(.005,abs(y-oy))
            changed=replace(mark,points=((left,top,1.),),box=(width,height))
            self.preview=replace(self.key,marks=tuple(changed if i==index else m for i,m in enumerate(self.key.marks)))
        elif self.gesture=='translate':
            dx,dy=point[0]-self.anchor[0],point[1]-self.anchor[1]
            points=[p for i in self.indices for p in mark_points(self.key.marks[i])]
            dx=max(-4-min(p[0] for p in points),min(dx,5-max(p[0] for p in points))); dy=max(-4-min(p[1] for p in points),min(dy,5-max(p[1] for p in points)))
            marks,self.preview_indices=move_erased_selection(self.key.marks,self.indices,dx,dy)
            self.preview=replace(self.key,marks=marks)
        self.c.invalidate()
    def finish(self):
        mode=self.gesture; self.gesture=None
        if mode=='lasso':
            self.path.closeSubpath(); self.indices=tuple(i for i,m in enumerate(self.key.marks) if m.tool!='eraser' and (self.path.intersects(self.geometry(m)) or self.path.contains(self.geometry(m)))); self.path=None
        elif mode in ('translate','resize_text'):
            preview=self.preview; self.preview=None; indices=self.indices
            if self.source is self.c.win.doc.state.drawings and preview!=self.key:
                self.c.commit_key(preview,'Redimensionner la zone de texte' if mode=='resize_text' else 'Déplacer le texte' if all(self.key.marks[i].tool=='text' for i in indices) else 'Déplacer les dessins')
                self.indices=getattr(self,'preview_indices',indices) if mode=='translate' else indices; self.key_start=preview.start; self.source=self.c.win.doc.state.drawings
        self.c.invalidate()
    def display_transform(self,rect):
        transform=QTransform(); transform.translate(rect.x(),rect.y()); transform.scale(rect.width(),rect.height())
        if self.c.viewer.flip_h: transform.translate(1,0); transform.scale(-1,1)
        if self.c.viewer.flip_v: transform.translate(0,1); transform.scale(1,-1)
        return transform
    def paint_outline(self,painter,rect,path):
        painter.save(); pen=QPen(QColor('#80eadb'),1.5,Qt.PenStyle.DashLine); pen.setCosmetic(True); painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.display_transform(rect).map(path)); painter.restore()
    def paint(self,painter,rect):
        if self.gesture=='lasso' and self.path: self.paint_outline(painter,rect,self.path)
        elif self.indices:
            bounds=self.bounds(self.preview); path=QPainterPath(); path.addRect(bounds); self.paint_outline(painter,rect,path)
            key=self.preview or active_key(self.c.win.doc.state.drawings,self.c.win.doc.state.position)
            if key and len(self.indices)==1 and self.indices[0]<len(key.marks) and key.marks[self.indices[0]].tool=='text' and key.marks[self.indices[0]].transform==IDENTITY:
                transform=self.display_transform(rect); painter.save(); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#80eadb')); radius=3.5/self.c.viewer.zoom
                for point in (bounds.topLeft(),bounds.topRight(),bounds.bottomLeft(),bounds.bottomRight()): painter.drawEllipse(transform.map(point),radius,radius)
                painter.restore()
