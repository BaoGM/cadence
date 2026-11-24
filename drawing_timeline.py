# SPDX-License-Identifier: GPL-3.0-only
from ui_text import tr
from PySide6.QtCore import QObject,QEvent,Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPen,QImage,QPainter
from PySide6.QtWidgets import QMenu
from drawing import active_key, relocate_keys, resize_key
from bisect import bisect_left
from drag import ContinuousDrag
from timeline_index import visible_keys
from math import floor,ceil

EXPOSURE_FILL=QColor('#465765')

class DrawingTimeline(QObject):
    def __init__(self,timeline):
        super().__init__(timeline); self.t=timeline; self.mode=None; self.preview=None; self.change=None; self.valid=True
        self.hover_handle=None; self.focus_handle=None
        timeline.setFocusPolicy(Qt.StrongFocus)
        timeline.installEventFilter(self)
    def focus_valid(self):
        state=self.t.state
        return bool(state and active_key(state.drawings,self.focus_key.start) is self.focus_key)
    def focus_part(self,key,part):
        if self.focus_handle is None:
            from handle_focus import HandleFocus
            self.focus_handle=HandleFocus(self.t,self.focus_valid,self.nudge,self.cycle_part)
        self.focus_part_name=part; self.focus_key=key
        title={'left':'Début','body':'Déplacer','right':'Fin'}[part]
        self.t.ensure_visible(key.end-1 if part=='right' else key.start)
        self.focus_handle.activate(f"{tr('Clés de dessin')} · {tr(title)} · {key.start}")
    def cycle_part(self,amount):
        parts=('left','body','right')
        index=parts.index(self.focus_part_name)+amount
        if not 0<=index<len(parts): return False
        self.focus_part(self.focus_key,parts[index]); return True
    def nudge(self,amount):
        t=self.t; key=self.focus_key; part=self.focus_part_name
        index=bisect_left(t.state.drawings,key.start,key=lambda k:k.start)
        if part=='body':
            t.drawingMoved.emit(key.start,key.end,key.start+amount)
        else:
            start=key.start+(amount if part=='left' else 0)
            end=key.end+(amount if part=='right' else 0)
            t.drawingResized.emit(key.start,start,end)
        if index<len(t.state.drawings):
            self.focus_part(t.state.drawings[index],part)
    def hit(self,x):
        t=self.t
        frame=t.raw_frame(x); margin=6*t.span()/t.track_width()
        candidates=list(visible_keys(t.state.drawings,frame-margin,frame+margin))
        candidates=[k for k in candidates if t.x_for(k.start)-6<=x<=t.x_for(k.end)+6]
        return min(candidates,key=lambda k:(max(t.x_for(k.start)-x,0,x-t.x_for(k.end)),abs(x-t.x_for((k.start+k.end)/2))),default=None)
    def contains(self,pos):
        t=self.t
        y=t.track_y('drawing')
        top,bottom=(y-3,y+6) if t.simple else (t.marker_lane_height,t.ruler_y()-1)
        return t.track_left()<=pos.x()<=t.track_right() and top<=pos.y()<=bottom
    def resize_mode(self,key,x):
        left,right=self.t.x_for(key.start),self.t.x_for(key.end)
        center=(left+right)/2
        half=max(5,(right-left)/2)
        grip=min(6,half*.45)
        if abs(x-center)<half-grip: return 'click'
        if key.end-key.start==1: return 'extend'
        return 'left' if x<center else 'right'
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
        if self.mode and (not t.state or self.source is not t.state.drawings or kind in (QEvent.Type.Hide,QEvent.Type.WindowDeactivate,QEvent.Type.FocusOut)):
            self.cancel()
            return False
        if not t.state or not t.state.length: return False
        if kind in (QEvent.ShortcutOverride,QEvent.KeyPress) and t.hasFocus() and not self.mode and t.state.drawings:
            if e.key() in (Qt.Key_Return,Qt.Key_Enter) and e.modifiers()==Qt.NoModifier:
                if kind==QEvent.KeyPress:
                    keys=t.state.drawings; frame=t.state.position
                    current=active_key(keys,frame)
                    if current is None:
                        idx=bisect_left(keys,frame,key=lambda k:k.start)
                        current=keys[min(idx,len(keys)-1)]
                    self.focus_part(current,'body')
                e.accept(); return True
        if kind==QEvent.Type.MouseButtonPress and e.button()==Qt.MouseButton.LeftButton:
            if not self.contains(e.position()):
                t.selection_track='audio' if e.position().y()>=t.track_y('audio')-4 else 'video'; return False
            t.setFocus(); t.selection_track='drawing'; self.key=self.hit(e.position().x()); self.source=t.state.drawings
            self.drag=ContinuousDrag(e.globalPosition()); self.scale=t.span()/t.track_width(); self.start_frame=t.frame_for(e.position().x()); self.preview=None; self.change=None; self.valid=True
            t.begin_range_drag(self.start_frame)
            if e.modifiers()&Qt.KeyboardModifier.AltModifier:
                if not self.key:
                    self.drag.finish()
                    if t.simple:
                        t.selection_track='video'
                        return False
                    return True
                self.mode='move'; self.span=t.state.selection if t.state.selection and t.state.selection[0]<=self.start_frame<t.state.selection[1] else (self.key.start,self.key.end)
            elif e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
                self.mode=t.update_range_drag(self.start_frame,e.modifiers())
            elif self.key:
                self.mode=self.resize_mode(self.key,e.position().x())
                self.span=(self.key.start,self.key.end)
            else: self.mode=t.update_range_drag(self.start_frame,e.modifiers())
            e.accept(); return True
        if kind==QEvent.Type.MouseMove:
            if not self.mode:
                self.hover_handle=None
                if self.contains(e.position()):
                    key=self.hit(e.position().x()); edge=key and self.resize_mode(key,e.position().x())!='click'
                    if edge: self.hover_handle=(key,'left' if e.position().x()<t.x_for((key.start+key.end)/2) else 'right')
                    t.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.OpenHandCursor if key else Qt.CursorShape.ArrowCursor)
                else: t.unsetCursor()
                return False
            distance=self.drag.move(e.globalPosition()).x()
            delta=round(distance*self.scale); n=t.state.length
            if self.mode in ('scrub','select') or self.mode=='click' and e.modifiers()&Qt.KeyboardModifier.ShiftModifier:
                frame=max(0,min(n-1,self.start_frame+delta)); t.ensure_visible(frame)
                self.mode=t.update_range_drag(frame,e.modifiers())
            elif self.mode=='move' or self.mode=='click' and abs(distance)>=3:
                self.mode='move'
                a,b=self.span; dest=max(0,min(n-(b-a),a+delta)); self.preview=relocate_keys(self.source,a,b,dest,n); self.valid=self.preview!=self.source or dest==a; self.change=(a,b,dest); t.ensure_visible(dest)
                t.setCursor(Qt.ClosedHandCursor if self.valid else Qt.ForbiddenCursor)
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
            elif mode=='click': t.seek.emit(self.key.start)
            t.unsetCursor(); t.update(); t.finish_range_drag()
            if not change and e.modifiers()==Qt.NoModifier and mode in ('click','left','right','extend'):
                part='body' if mode=='click' else mode
                if part=='extend': part='left' if e.position().x()<t.x_for((self.key.start+self.key.end)/2) else 'right'
                self.focus_part(self.key,part)
            e.accept(); return True
        if kind==QEvent.Type.ShortcutOverride and e.key()==Qt.Key.Key_Escape and self.mode:
            e.accept(); return True
        if kind==QEvent.Type.KeyPress and e.key()==Qt.Key.Key_Escape and self.mode:
            self.cancel(); e.accept(); return True
        return False
    def cancel(self):
        self.drag.finish(); self.mode=None; self.preview=None; self.change=None
        self.t.unsetCursor(); self.t.update(); self.t.finish_range_drag()
    def simple_markers(self,keys=None):
        t=self.t; left=t.track_left(); right=left+t.track_width()
        scale=t.track_width()/t.span(); last_pixel=None
        for key in visible_keys(t.state.drawings if keys is None else keys,t.view_start,t.view_start+t.span()):
            if not key.marks or key.end<=t.view_start or key.start>=t.view_start+t.span(): continue
            x1=max(left,left+(key.start-t.view_start)*scale)
            x2=min(right,max(x1+3,left+(key.end-t.view_start)*scale))
            if (key.end-key.start)*scale<1 and floor(x1)==last_pixel: continue
            last_pixel=floor(x1)
            yield QRectF(x1,t.track_y('drawing'),max(1,x2-x1),4)
    def paint_simple(self,p):
        p.save(); p.setClipRect(QRectF(self.t.track_left(),self.t.track_y('drawing')-3,self.t.track_width(),12))
        keys=self.preview if self.preview is not None else self.t.state.drawings
        self.paint_cached(p,keys,True)
        p.restore()
    def paint_cached(self,p,keys,simple=False):
        t=self.t; ratio=t.devicePixelRatioF(); y=t.track_y('drawing')-3 if simple else t.marker_lane_height
        lane_height=10 if simple else t.drawing_lane_height
        if t.selection_track=='drawing' and t.state.selection:
            a,b=t.state.selection
            left=max(t.track_left(),t.x_for(a)); right=min(t.track_right(),t.x_for(b))
            if right>left:
                height=lane_height-1
                p.fillRect(QRectF(left,y,right-left,height),QColor(104,224,207,96))
                p.fillRect(QRectF(left,y+height-1,right-left,1),QColor('#68e0cf'))
        signature=(id(keys),t.width(),ratio,t.view_start,t.span(),simple,y,p.font().toString())
        cached=getattr(self,'raster',None)
        if cached is None or cached[0]!=signature:
            image=QImage(ceil(t.width()*ratio),ceil(lane_height*ratio),QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio); image.fill(Qt.GlobalColor.transparent)
            ink=QPainter(image); ink.setRenderHints(p.renderHints()); ink.setFont(p.font()); ink.translate(0,-y)
            self.paint_keys(ink,keys,simple,None)
            ink.end(); self.raster=(signature,keys,image)
        p.drawImage(QPointF(0,y),self.raster[2])
        current=active_key(keys,t.state.position)
        if current: self.paint_keys(p,(current,),simple,current.start)
        if self.focus_handle is not None and self.focus_handle.hasFocus() and self.focus_valid():
            k=self.focus_key
            mid=t.x_for((k.start+k.end)/2); half=max(5,(t.x_for(k.end)-t.x_for(k.start))/2)
            area=QRectF(mid-half,y+.5,half*2,lane_height-1)
            if self.focus_part_name!='body':
                x=area.left() if self.focus_part_name=='left' else area.right()
                area=QRectF(x-2.5,area.top(),5,area.height())
            p.setPen(QPen(QColor('#ffcf96'),1.6)); p.setBrush(Qt.NoBrush); p.drawRoundedRect(area,2,2)
        if self.hover_handle and self.mode is None:
            key,edge=self.hover_handle
            if key in visible_keys(keys,key.start,key.end):
                middle=t.x_for((key.start+key.end)/2)
                dx=max(5,(t.x_for(key.end)-t.x_for(key.start))/2)-1
                x=middle-dx if edge=='left' else middle+dx
                top=t.track_y('drawing')-(0 if simple else 6)
                p.setPen(QPen(QColor('#e1faf4'),2.6,Qt.SolidLine,Qt.RoundCap))
                p.drawLine(QPointF(x,top-1),QPointF(x,top+(5 if simple else 13)))
    def paint(self,p):
        t=self.t
        if not t.state.drawings:
            self.raster=None; return
        y=t.track_y('drawing')
        p.save(); p.setClipRect(QRectF(t.track_left(),t.marker_lane_height,t.track_width(),t.drawing_lane_height))
        keys=self.preview if self.preview is not None else t.state.drawings
        self.paint_cached(p,keys)
        if self.change:
            a,b,c=self.change; text=f'→ {c}' if self.mode=='move' else f'{b} → {c-1}'
            if not self.valid: text='Emplacement occupé'
            p.setClipping(False); p.setPen(QColor('#ff7f70' if not self.valid else '#ffe0a0')); p.drawText(QRectF(t.track_left(),y+7,300,20),Qt.AlignmentFlag.AlignVCenter,tr(text))
        p.restore()
    def paint_keys(self,p,keys,simple=False,active_start=None):
        t=self.t; y=t.track_y('drawing')-(0 if simple else 6)
        left,right=t.track_left(),t.track_right(); scale=t.track_width()/t.span(); last_pixel=None
        for key in visible_keys(keys,t.view_start-13/scale,t.view_start+t.span()):
            x1=left+(key.start-t.view_start)*scale; x2=left+(key.end-t.view_start)*scale
            if x2-x1<1 and floor(x1)==last_pixel: continue
            last_pixel=floor(x1)
            if x2-x1<10:
                mid=(x1+x2)/2; x1=mid-5; x2=mid+5
            width=x2-x1-1
            if x1+max(width,6)<left or x1>right: continue
            active=key.start==active_start
            fill=QColor('#3b6869') if active else EXPOSURE_FILL
            edge=QColor('#94ded4' if active else '#849aab')
            if not key.marks:
                fill=QColor('#303d48')
            height=4 if simple else 12
            p.setBrush(fill)
            p.setPen(QPen(edge,1))
            p.drawRoundedRect(QRectF(x1+.5,y+.5,width,height),1.5,1.5)
            p.setPen(QPen(QColor('#d8f1ed' if active else '#becbd4'),1.5,Qt.SolidLine,Qt.RoundCap))
            for x in (x1+1,x2-1):
                p.drawLine(QPointF(x,y-1),QPointF(x,y+height+1))
