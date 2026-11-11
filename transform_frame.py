# SPDX-License-Identifier: GPL-3.0-only
import math
from PySide6.QtCore import QPointF,QRectF,Qt
from affine import qt,rotate,compose,translate,scale

_rotation_cursor=None
def rotation_cursor():
    global _rotation_cursor
    if _rotation_cursor is None:
        from PySide6.QtGui import QCursor,QPixmap,QPainter,QPen,QColor
        pixmap=QPixmap(28,28); pixmap.fill(Qt.GlobalColor.transparent); p=QPainter(pixmap); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#dce4ee'),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawArc(5,5,17,17,35*16,290*16)
        p.drawLine(21,7,21,13); p.drawLine(21,13,16,11); p.end(); _rotation_cursor=QCursor(pixmap,14,14)
    return _rotation_cursor

class TransformFrame:
    def __init__(self,rect,aspect,angle=0,centered=False):
        self.rect=QRectF(rect); self.aspect=aspect; self.angle=angle; self.centered=centered; self.drag=None
    def matrix(self): return qt(rotate(self.angle,self.rect.center(),self.aspect))
    def handles(self):
        r=self.rect
        points=[r.topLeft(),QPointF(r.center().x(),r.top()),r.topRight(),QPointF(r.right(),r.center().y()),r.bottomRight(),QPointF(r.center().x(),r.bottom()),r.bottomLeft(),QPointF(r.left(),r.center().y())]
        return [self.matrix().map(p) for p in points]
    def hit(self,p,sx,sy,rotation=True):
        distances=[math.hypot((p.x()-q.x())*sx,(p.y()-q.y())*sy) for q in self.handles()]
        index=min(range(8),key=lambda i:distances[i])
        if distances[index]<=9: return index
        local=self.matrix().inverted()[0].map(p)
        if rotation and not self.rect.contains(local) and min(distances[i] for i in (0,2,4,6))<=30: return 'rotate'
        if self.rect.contains(local): return 'move'
        return None
    def begin(self,kind,p,mods):
        self.drag=dict(kind=kind,base=QRectF(self.rect),angle=self.angle,anchor=p,last=p,mods=mods)
    def update(self,p,mods):
        d=self.drag
        if not d: return
        # Rebase when switching Alt/Ctrl so the current frame does not jump.
        flags=Qt.KeyboardModifier.AltModifier|Qt.KeyboardModifier.ControlModifier
        if (mods&flags)!=(d['mods']&flags):
            d.update(base=QRectF(self.rect),angle=self.angle,anchor=d['last'],mods=mods)
        r=d['base']; a=d['anchor']; kind=d['kind']; angle=d['angle']; delta=p-a
        if mods&Qt.KeyboardModifier.AltModifier or kind=='move': self.rect=r.translated(delta)
        elif kind=='new': self.rect=QRectF(a,p).normalized()
        elif kind=='rotate':
            c=r.center()
            def heading(q): return math.degrees(math.atan2(q.y()-c.y(),(q.x()-c.x())*self.aspect))
            value=angle+(heading(p)-heading(a)+180)%360-180
            if mods&Qt.KeyboardModifier.ShiftModifier: value=round(value/15)*15
            self.angle=(value+180)%360-180
        else:
            inverse=qt(rotate(-angle,r.center(),self.aspect)); diff=inverse.map(p)-inverse.map(a)
            l,t,rr,b=r.left(),r.top(),r.right(),r.bottom(); centered=self.centered or bool(mods&Qt.KeyboardModifier.ControlModifier)
            if kind in (0,6,7): l+=diff.x(); rr-=diff.x() if centered else 0
            if kind in (2,3,4): rr+=diff.x(); l-=diff.x() if centered else 0
            if kind in (0,1,2): t+=diff.y(); b-=diff.y() if centered else 0
            if kind in (4,5,6): b+=diff.y(); t-=diff.y() if centered else 0
            if rr-l<.002 or b-t<.002: return
            if mods&Qt.KeyboardModifier.ShiftModifier:
                width,height=rr-l,b-t; ratio=r.width()/r.height()
                if kind in (1,5): width=height*ratio
                else: height=width/ratio
                if centered: l=r.center().x()-width/2; rr=l+width; t=r.center().y()-height/2; b=t+height
                else:
                    if kind in (0,6,7): l=rr-width
                    else: rr=l+width
                    if kind in (0,1,2): t=b-height
                    else: b=t+height
            new=QRectF(l,t,rr-l,b-t); center=qt(rotate(angle,r.center(),self.aspect)).map(new.center()); new.moveCenter(center); self.rect=new
        d['last']=p
    def delta(self,original,original_angle=0):
        old=original.center(); new=self.rect.center()
        matrix=translate(-old.x(),-old.y())
        matrix=compose(rotate(-original_angle,QPointF(),self.aspect),matrix)
        matrix=compose(scale(self.rect.width()/original.width(),self.rect.height()/original.height(),QPointF()),matrix)
        matrix=compose(rotate(self.angle,QPointF(),self.aspect),matrix)
        return compose(translate(new.x(),new.y()),matrix)
