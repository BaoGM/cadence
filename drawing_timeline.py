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
        frame=t.raw_frame(x); margin=4*t.span()/t.track_width()
        candidates=list(visible_keys(t.state.drawings,frame-margin,frame+margin))
        return next((k for k in reversed(candidates) if t.x_for(k.start)-4<=x<=max(t.x_for(k.start)+4,t.x_for(k.end))),None)
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
        if kind==QEvent.Type.ContextMenu and e.pos().y()>=t.track_y('drawing')-3:
            menu=self.context_menu(e.pos().x())
            menu.exec(e.globalPos()); menu.deleteLater()
            e.accept(); return True
        if kind==QEvent.Type.MouseButtonPress and e.button()==Qt.MouseButton.LeftButton:
            if e.position().y()<t.track_y('drawing')-3:
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
                x=e.position().x(); left,right=t.x_for(self.key.start),t.x_for(self.key.end)
                self.mode=('left' if abs(x-left)<=abs(x-right) else 'right') if min(abs(x-left),abs(x-right))<=6 else 'click'
                t.selected.emit(self.key.start,self.key.end)
            else: self.mode=t.update_range_drag(self.start_frame,e.modifiers())
            e.accept(); return True
        if kind==QEvent.Type.MouseMove:
            if not self.mode:
                if e.position().y()>=t.track_y('drawing')-3:
                    key=self.hit(e.position().x()); edge=key and min(abs(e.position().x()-t.x_for(key.start)),abs(e.position().x()-t.x_for(key.end)))<=6
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
            elif self.mode in ('left','right'):
                a,b=self.key.start,self.key.end
                self.preview=resize_key(self.source,a,a+delta if self.mode=='left' else a,b+delta if self.mode=='right' else b,n)
                index=self.source.index(self.key); key=self.preview[index]; self.change=(a,key.start,key.end); t.ensure_visible(key.start if self.mode=='left' else key.end-1)
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
                elif mode in ('left','right'): t.drawingResized.emit(*change)
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
        t=self.t; ratio=t.devicePixelRatioF(); y=t.simple_track_rect().top()-2 if simple else t.track_y('drawing')-4
        signature=(id(keys),t.width(),ratio,t.view_start,t.span(),simple,p.font().toString())
        cached=getattr(self,'raster',None)
        if cached is None or cached[0]!=signature:
            image=QImage(ceil(t.width()*ratio),ceil(29*ratio),QImage.Format.Format_ARGB32_Premultiplied)
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
        p.setClipping(False); p.setPen(QColor('#8895a7')); p.drawText(QRectF(0,y,t.track_left(),19),Qt.AlignmentFlag.AlignCenter,tr('DESSIN')); p.setClipRect(QRectF(t.track_left(),y-4,t.track_width(),29))
        keys=self.preview if self.preview is not None else t.state.drawings
        self.paint_cached(p,keys)
        if t.state.selection:
            a,b=t.state.selection; left=max(t.track_left(),t.x_for(a)); right=min(t.track_right(),t.x_for(b))
            if right>left: p.fillRect(QRectF(left,y-1,right-left,21),QColor(104,224,207,45))
        p.setPen(QPen(QColor('#ffffff'),2)); p.drawLine(QPointF(t.x_for(t.state.position),y-3),QPointF(t.x_for(t.state.position),y+23))
        if self.change:
            a,b,c=self.change; text=f'→ {c}' if self.mode=='move' else f'{b} → {c-1}'
            if not self.valid: text='Emplacement occupé'
            p.setClipping(False); p.setPen(QColor('#ff7f70' if not self.valid else '#ffe0a0')); p.drawText(QRectF(80,y-6,300,20),Qt.AlignmentFlag.AlignVCenter,tr(text))
        p.setClipping(False)
    def paint_keys(self,p,keys):
        t=self.t; y=t.track_y('drawing')
        left,right=t.track_left(),t.track_right(); scale=t.track_width()/t.span(); last_pixel=None
        for key in visible_keys(keys,t.view_start-13/scale,t.view_start+t.span()):
            x1=left+(key.start-t.view_start)*scale; x2=left+(key.end-t.view_start)*scale; width=max(4,x2-x1-1)
            if x1+max(width,13)<left or x1>right: continue
            if x2-x1<1 and floor(x1)==last_pixel: continue
            last_pixel=floor(x1)
            p.fillRect(QRectF(x1,y,width,19),QColor('#66533c' if key.marks else '#303743'))
            if x2-x1>=1:
                p.setPen(QColor('#f4bc70')); p.drawText(QRectF(x1+3,y-1,max(10,width),20),Qt.AlignmentFlag.AlignVCenter,tr('◆'))
            p.setPen(QPen(DRAWING_GOLD,2)); p.drawLine(QPointF(x1+1,y+3),QPointF(x1+1,y+16)); p.drawLine(QPointF(x1+width-1,y+3),QPointF(x1+width-1,y+16))
