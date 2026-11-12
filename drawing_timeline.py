# SPDX-License-Identifier: GPL-3.0-only
from ui_text import tr
from PySide6.QtCore import QObject,QEvent,Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPen,QImage,QPainter
from PySide6.QtWidgets import QMenu
from drawing import relocate_keys, resize_key
from drag import ContinuousDrag
from timeline_index import visible_keys
from math import floor,ceil

DRAWING_GOLD=QColor('#e9b566')

class DrawingTimeline(QObject):
    def __init__(self,timeline):
        super().__init__(timeline); self.t=timeline; self.mode=None; self.preview=None; self.change=None; self.valid=True
        timeline.installEventFilter(self)
    def hit(self,x):
        t=self.t
        frame=t.raw_frame(x); margin=6*t.span()/t.track_width()
        candidates=list(visible_keys(t.state.drawings,frame-margin,frame+margin))
        candidates=[k for k in candidates if t.x_for(k.start)-6<=x<=t.x_for(k.end)+6]
        return min(candidates,key=lambda k:(max(t.x_for(k.start)-x,0,x-t.x_for(k.end)),abs(x-t.x_for((k.start+k.end)/2))),default=None)
    def contains(self,pos):
        t=self.t
        return t.track_left()<=pos.x()<=t.track_right() and t.track_y('drawing')-3<=pos.y()<=t.track_y('drawing')+6
    def resize_mode(self,key,x):
        if key.end-key.start==1: return 'extend'
        left,right=self.t.x_for(key.start),self.t.x_for(key.end)
        return ('left' if abs(x-left)<=abs(x-right) else 'right') if min(abs(x-left),abs(x-right))<=6 else 'click'
    def context_menu(self,x):
        t=self.t; frame=t.frame_for(x); key=self.hit(x); selection=t.state.selection
        span=selection if selection and selection[0]<=frame<selection[1] else (key.start,key.end) if key else None
        t.selection_track='drawing'
        menu=QMenu(t); t.add_units(menu); menu.addSeparator(); t.add_timeline_mode(menu); menu.addSeparator()
        has_keys=bool(span and any(k.start<span[1] and k.end>span[0] for k in t.state.drawings))
        clipboard_length=getattr(t,'drawing_clipboard_length',0)
        commands=[('paste','Coller la clé'),('copy','Copier la clé'),('cut','Couper la clé')]
        for operation,title in sorted(commands,key=lambda item:tr(item[1]).casefold()):
            action=menu.addAction(tr(title)); action.setData(operation)
            registered=getattr(t,'drawing_actions',{}).get(operation)
            if registered: action.setShortcut(registered.shortcut())
            enabled=bool(clipboard_length and frame+clipboard_length<=t.state.length) if operation=='paste' else has_keys
            action.setEnabled(enabled)
            a,b=(frame,frame) if operation=='paste' else span or (frame,frame+1)
            action.triggered.connect(lambda checked=False,op=operation,start=a,end=b:t.drawingClipboardRequested.emit(op,start,end))
        menu.addSeparator(); action=menu.addAction(tr('Supprimer les clés')); action.setEnabled(has_keys)
        if span: action.triggered.connect(lambda:t.drawingDelete.emit(*span))
        t.add_marker_actions(menu,x)
        return menu
    def eventFilter(self,obj,e):
        t=self.t; kind=e.type()
        if not t.state or not t.state.length: return False
        if getattr(t,'simple',False):
            if kind==QEvent.Type.MouseButtonPress and e.button()==Qt.MouseButton.LeftButton: t.selection_track='video'
            return False
        if kind==QEvent.Type.MouseButtonPress and e.button()==Qt.MouseButton.LeftButton:
            if not self.contains(e.position()):
                t.selection_track='audio' if e.position().y()>=t.track_y('audio')-4 else 'video'; return False
            t.setFocus(); t.selection_track='drawing'; self.key=self.hit(e.position().x()); self.source=t.state.drawings
            self.drag=ContinuousDrag(e.globalPosition()); self.scale=t.span()/t.track_width(); self.start_frame=t.frame_for(e.position().x()); self.preview=None; self.change=None; self.valid=True
            t.begin_range_drag(self.start_frame)
            if e.modifiers()&Qt.KeyboardModifier.AltModifier:
                if not self.key: return True
                self.mode='move'; self.span=t.state.selection if t.state.selection and t.state.selection[0]<=self.start_frame<t.state.selection[1] else (self.key.start,self.key.end)
            elif e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
                self.mode=t.update_range_drag(self.start_frame,e.modifiers())
            elif self.key:
                self.mode=self.resize_mode(self.key,e.position().x())
                t.selected.emit(self.key.start,self.key.end)
            else: self.mode=t.update_range_drag(self.start_frame,e.modifiers())
            e.accept(); return True
        if kind==QEvent.Type.MouseMove:
            if not self.mode:
                if self.contains(e.position()):
                    key=self.hit(e.position().x()); edge=key and self.resize_mode(key,e.position().x())!='click'
                    t.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.ArrowCursor)
                else: t.unsetCursor()
                return False
            delta=round(self.drag.move(e.globalPosition()).x()*self.scale); n=t.state.length
            if self.mode in ('scrub','select') or self.mode=='click' and e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
                frame=max(0,min(n-1,self.start_frame+delta)); t.ensure_visible(frame)
                self.mode=t.update_range_drag(frame,e.modifiers())
            elif self.mode=='click': t.range_frame=max(0,min(n-1,self.start_frame+delta))
            elif self.mode=='move':
                a,b=self.span; dest=max(0,min(n-(b-a),a+delta)); self.preview=relocate_keys(self.source,a,b,dest,n); self.valid=self.preview!=self.source or dest==a; self.change=(a,b,dest); t.ensure_visible(dest)
            elif self.mode in ('left','right','extend'):
                a,b=self.key.start,self.key.end
                new_start=a+delta if self.mode=='left' else a+min(0,delta) if self.mode=='extend' else a
                new_end=b+delta if self.mode=='right' else b+max(0,delta) if self.mode=='extend' else b
                self.preview=resize_key(self.source,a,new_start,new_end,n)
                index=self.source.index(self.key); key=self.preview[index]; self.change=(a,key.start,key.end); t.ensure_visible(key.start if self.mode=='left' or self.mode=='extend' and delta<0 else key.end-1)
            t.update(); e.accept(); return True
        if kind in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease) and e.key()==Qt.Key.Key_Shift and self.mode in ('scrub','select','click'):
            if not e.isAutoRepeat():
                modifiers=e.modifiers()|Qt.KeyboardModifier.ShiftModifier if kind==QEvent.Type.KeyPress else e.modifiers()&~Qt.KeyboardModifier.ShiftModifier
                self.mode=t.update_range_drag(t.range_frame,modifiers)
            e.accept(); return True
        if kind==QEvent.Type.MouseButtonRelease and e.button()==Qt.MouseButton.LeftButton and self.mode:
            self.drag.finish(); mode=self.mode; change=self.change; valid=self.valid; self.mode=None; self.preview=None; self.change=None
            if change and valid:
                if mode=='move': t.drawingMoved.emit(*change)
                elif mode in ('left','right','extend'): t.drawingResized.emit(*change)
            t.update(); t.finish_range_drag(); e.accept(); return True
        if kind==QEvent.Type.KeyPress and e.key()==Qt.Key.Key_Escape and self.mode:
            self.drag.finish(); self.mode=None; self.preview=None; self.change=None; t.update(); t.finish_range_drag(); e.accept(); return True
        return False
    def simple_markers(self):
        t=self.t; left=t.track_left(); right=left+t.track_width()
        scale=t.track_width()/t.span(); last_pixel=None
        for key in visible_keys(t.state.drawings,t.view_start,t.view_start+t.span()):
            if not key.marks or key.end<=t.view_start or key.start>=t.view_start+t.span(): continue
            x1=max(left,left+(key.start-t.view_start)*scale)
            x2=min(right,max(x1+3,left+(key.end-t.view_start)*scale))
            if (key.end-key.start)*scale<1 and floor(x1)==last_pixel: continue
            last_pixel=floor(x1)
            yield QRectF(x1,t.simple_track_rect().top(),max(1,x2-x1),4)
    def paint_simple(self,p):
        p.save(); p.setClipRect(self.t.simple_track_rect())
        self.paint_cached(p,self.t.state.drawings,True)
        p.restore()
    def paint_cached(self,p,keys,simple=False):
        t=self.t; ratio=t.devicePixelRatioF(); y=t.simple_track_rect().top()-2 if simple else t.track_y('drawing')-2
        signature=(id(keys),t.width(),ratio,t.view_start,t.span(),simple,p.font().toString())
        cached=getattr(self,'raster',None)
        if cached is None or cached[0]!=signature:
            image=QImage(ceil(t.width()*ratio),ceil(8*ratio),QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio); image.fill(Qt.GlobalColor.transparent)
            ink=QPainter(image); ink.setRenderHints(p.renderHints()); ink.setFont(p.font()); ink.translate(0,-y)
            if simple:
                for rect in self.simple_markers(): ink.fillRect(rect,DRAWING_GOLD)
            else: self.paint_keys(ink,keys)
            ink.end(); self.raster=(signature,keys,image)
        p.drawImage(QPointF(0,y),self.raster[2])
    def paint(self,p):
        t=self.t
        if not t.state.drawings:
            self.raster=None; return
        y=t.track_y('drawing')
        p.save(); p.setClipRect(QRectF(t.track_left(),y-2,t.track_width(),8))
        keys=self.preview if self.preview is not None else t.state.drawings
        self.paint_cached(p,keys)
        if t.state.selection:
            a,b=t.state.selection; left=max(t.track_left(),t.x_for(a)); right=min(t.track_right(),t.x_for(b))
            if right>left: p.fillRect(QRectF(left,y-1,right-left,6),QColor(104,224,207,45))
        if self.change:
            a,b,c=self.change; text=f'→ {c}' if self.mode=='move' else f'{b} → {c-1}'
            if not self.valid: text='Emplacement occupé'
            p.setClipping(False); p.setPen(QColor('#ff7f70' if not self.valid else '#ffe0a0')); p.drawText(QRectF(t.track_left(),y+7,300,20),Qt.AlignmentFlag.AlignVCenter,tr(text))
        p.restore()
    def paint_keys(self,p,keys):
        t=self.t; y=t.track_y('drawing')
        left,right=t.track_left(),t.track_right(); scale=t.track_width()/t.span(); last_pixel=None
        for key in visible_keys(keys,t.view_start-13/scale,t.view_start+t.span()):
            x1=left+(key.start-t.view_start)*scale; x2=left+(key.end-t.view_start)*scale; width=max(3,x2-x1-1)
            if x1+max(width,6)<left or x1>right: continue
            if x2-x1<1 and floor(x1)==last_pixel: continue
            last_pixel=floor(x1)
            p.fillRect(QRectF(x1,y,width,4),QColor('#ad8954' if key.marks else '#58616e'))
            handles=[(x1+x2)/2] if key.end-key.start==1 else [x1,x2]
            p.setPen(QPen(DRAWING_GOLD,2))
            for x in handles: p.drawLine(QPointF(x,y-1),QPointF(x,y+5))
