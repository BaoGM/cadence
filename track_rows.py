# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPen,QPainterPath
from PySide6.QtWidgets import QMenu
from model import MediaTrack,TrackInfo
from ui_text import tr


class TrackRows:
    @property
    def active_media(self):
        if self.state is None: return MediaTrack(TrackInfo())
        return next((t for t in self.state.tracks if t.info.id==getattr(self,'active_media_id',None)),self.state.tracks[0])

    def media_rows(self):
        y=47
        for track in self.state.tracks if self.state else ():
            height=52 if track.info.audio_expanded else 26
            yield track,y,height
            y+=height+7

    def media_row_at(self,y):
        return next((track for track,top,height in self.media_rows() if top-3<=y<top+height),None)

    def media_track_y(self,kind):
        top=next((y for track,y,height in self.media_rows() if track.info.id==self.active_media.info.id),47)
        return (34 if self.simple else 40) if kind=='drawing' else top+26 if kind=='audio' else top

    def media_height(self):
        return max((y+height+7 for track,y,height in self.media_rows()),default=73)

    def activate_media_row(self,y):
        if self.simple: return
        track=self.media_row_at(y)
        if track is not None and track.info.id!=getattr(self,'active_media_id',None):
            self.active_media_id=track.info.id
            self.mediaTrackSelected.emit(track.info.id,'activate')

    def press_media_title(self,event):
        if self.simple or event.button()!=Qt.MouseButton.LeftButton or event.position().x()>=self.track_left(): return False
        track=self.media_row_at(event.position().y())
        if track is None: return False
        if event.position().x()<18 and event.modifiers()==Qt.NoModifier:
            self.mediaAudioExpanded.emit(track.info.id,not track.info.audio_expanded)
        else:
            self.active_media_id=track.info.id
            self.mediaTrackSelected.emit(track.info.id,'toggle' if event.modifiers()&Qt.KeyboardModifier.ControlModifier else 'replace')
            self.media_title_drag=(track.info.id,event.position().y())
        event.accept()
        return True

    def toggle_media_selection(self,event):
        if self.simple or event.button()!=Qt.MouseButton.LeftButton or not event.modifiers()&Qt.KeyboardModifier.ControlModifier: return False
        track=self.media_row_at(event.position().y())
        if track is None: return False
        self.mediaTrackSelected.emit(track.info.id,'toggle')
        event.accept(); return True

    def begin_cross_drag(self,event):
        self.cross_origin=None; self.cross_target=None; self.cross_copy=False
        if self.simple or len(getattr(self,'selected_media_ids',()))!=2: return
        target=self.context_target(event.position().x(),event.position().y(),False)
        if target is None: return
        a,b,kind=target
        from model import locate
        if all(locate(segments,a)[0] is None for segments in (self.active_media.segments,self.active_media.audio)): return
        self.cross_origin=(self.active_media.info.id,a,b)

    def update_cross_drag(self,event,x):
        origin=getattr(self,'cross_origin',None)
        if origin is None or self.gesture not in ('scrub','move','copy','transfer'): return False
        target=self.media_row_at(event.position().y())
        if target is None or target.info.id==origin[0]:
            self.cross_target=None
            if self.gesture=='transfer': self.update(); return True
            return False
        self.cross_target=target.info.id
        if self.gesture!='transfer':
            self.cross_copy=self.gesture=='copy'
            if self.move_span: self.cross_origin=(origin[0],self.move_span[0],self.move_span[1])
            else:
                self.move_span=(origin[1],origin[2],'video')
                self.grab_offset=self.x_for(self.anchor)-self.x_for(origin[1])
            self.gesture='transfer'; self.finish_range_drag()
        frame=max(0,min(self.state.length,round(self.raw_frame(x)))); at=0
        for segment in target.segments:
            end=at+segment.length
            if at<frame<end and segment.media is not None:
                frame=at if frame-at<=end-frame else end; break
            at=end
        self.drag_animation.stop(); self.drop_frame=frame; self.animated_x=self.x_for(frame)
        self.ghost_x=x-self.grab_offset; self.update(); return True

    def release_media_title(self,event):
        drag=getattr(self,'media_title_drag',None)
        if drag is None: return False
        self.media_title_drag=None
        target=self.media_row_at(event.position().y())
        if target and target.info.id!=drag[0] and abs(event.position().y()-drag[1])>=5:
            self.mediaTrackReordered.emit(drag[0],1 if event.position().y()>drag[1] else -1)
        event.accept()
        return True

    def paint_media_titles(self,painter):
        selected=getattr(self,'selected_media_ids',(self.active_media.info.id,))
        for index,(track,y,height) in enumerate(self.media_rows()):
            active=track.info.id in selected
            area=QRectF(1,y-3,self.track_left()-4,height)
            painter.setPen(QPen(QColor('#68e0cf' if active else '#35434e'),1))
            painter.setBrush(QColor('#243a43' if active else '#17212a'))
            painter.drawRoundedRect(area,3,3)
            painter.setPen(QColor('#d5eaf1' if active else '#91a1b5'))
            path=QPainterPath()
            points=((6,y+7),(10,y+11),(14,y+7)) if track.info.audio_expanded else ((8,y+5),(12,y+9),(8,y+13))
            path.moveTo(QPointF(*points[0]))
            for point in points[1:]: path.lineTo(QPointF(*point))
            painter.setPen(QPen(QColor('#d5eaf1' if active else '#91a1b5'),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
            painter.drawText(QRectF(18,y,self.track_left()-24,19),Qt.AlignmentFlag.AlignCenter,tr(track.info.name))
            if track.info.audio_expanded:
                if not track.info.audio_enabled: painter.setPen(QColor('#85888d'))
                painter.drawText(QRectF(18,y+26,self.track_left()-24,19),Qt.AlignmentFlag.AlignCenter,tr('AUDIO'))
            painter.setPen(QColor('#27313e'))
            if index: painter.drawLine(0,y-7,self.width(),y-7)

    def media_header_menu(self,pos):
        if self.simple or pos.x()>=self.track_left(): return None
        track=self.media_row_at(pos.y())
        if track is None: return None
        self.active_media_id=track.info.id
        self.mediaTrackSelected.emit(track.info.id,'activate')
        menu=QMenu(self)
        self.add_media_audio_action(menu,track)
        menu.addAction(tr('Utiliser comme référence B'),lambda:self.mediaReferenceRequested.emit(track.info.id))
        menu.addAction(tr('Replier l’audio' if track.info.audio_expanded else 'Déployer l’audio'),
                       lambda:self.mediaAudioExpanded.emit(track.info.id,not track.info.audio_expanded))
        menu.addSeparator()
        for direction,title in ((-1,'Monter la piste'),(1,'Descendre la piste')):
            action=menu.addAction(tr(title),lambda checked=False,d=direction:self.mediaTrackReordered.emit(track.info.id,d))
            index=next(i for i,t in enumerate(self.state.tracks) if t.info.id==track.info.id)
            action.setEnabled(0<=index+direction<len(self.state.tracks))
        menu.addSeparator()
        action=menu.addAction(tr('Ajouter une piste média'),self.mediaTrackAdded.emit)
        action.setEnabled(self.state.second_track is None)
        menu.addAction(tr('Supprimer la piste média'),lambda:self.mediaTrackRemoved.emit(track.info.id))
        return menu

    def add_media_audio_action(self,menu,track):
        action=menu.addAction(tr('Désactiver l’audio de la piste' if track.info.audio_enabled else 'Activer l’audio de la piste'))
        action.setData('track_audio')
        action.triggered.connect(lambda:self.mediaAudioEnabled.emit(track.info.id,not track.info.audio_enabled))
