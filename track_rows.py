# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu
from model import MediaTrack,TrackInfo
from ui_text import tr


class TrackRows:
    marker_lane_height=22
    drawing_lane_height=17

    def ruler_y(self):
        return 0 if self.simple else self.marker_lane_height+self.drawing_lane_height

    def ruler_height(self):
        return 23 if self.simple else 26

    def media_top(self):
        return self.ruler_y()+self.ruler_height()

    @property
    def active_media(self):
        if self.state is None: return MediaTrack(TrackInfo())
        return next((t for t in self.state.tracks if t.info.id==getattr(self,'active_media_id',None)),self.state.tracks[0])

    def media_rows(self):
        y=self.media_top()+3
        for track in self.state.tracks if self.state else ():
            height=self.video_height(track)+(22 if track.info.audio_expanded else 0)
            yield track,y,height
            y+=height

    def video_height(self,track):
        host=self.window()
        if host is not self and host.height()<=620:
            if host.height()<=440: return 44 if track.info.audio_expanded else 32
            return 45 if track.info.audio_expanded else 34
        return 57 if track.info.audio_expanded else 46

    def media_row_at(self,y):
        return next((track for track,top,height in self.media_rows() if top-3<=y<top+height-3),None)

    def media_track_y(self,kind):
        if self.simple:
            if kind=='drawing': return 17
            row=self.simple_track_rect()
            return int(row.bottom() if kind=='audio' else row.top())
        top=next((y for track,y,height in self.media_rows() if track.info.id==self.active_media.info.id),self.media_top()+3)
        return self.marker_lane_height+self.drawing_lane_height//2 if kind=='drawing' else top+self.video_height(self.active_media) if kind=='audio' else top

    def media_height(self):
        return max((y+height-3 for track,y,height in self.media_rows()),default=116)

    def activate_media_row(self,y):
        if self.simple: return
        track=self.media_row_at(y)
        if track is not None and track.info.id!=getattr(self,'active_media_id',None):
            self.active_media_id=track.info.id
            self.mediaTrackSelected.emit(track.info.id,'activate')

    def can_add_at_cursor(self,marker):
        if not self.state or not self.state.length: return False
        if marker and self.state.selection: return True
        frame=self.state.position
        if not 0<=frame<self.state.length: return False
        if marker:
            from bisect import bisect_left
            points=self.state.frame_markers
            i=bisect_left(points,frame)
            return i==len(points) or points[i]!=frame
        from drawing import active_key
        return active_key(self.state.drawings,frame) is None

    def press_media_title(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or event.position().x()>=self.track_left(): return False
        x,y=event.position().x(),event.position().y()
        if self.simple:
            if self.state and y>=self.media_top() and event.modifiers()==Qt.ControlModifier:
                self.mediaTrackSelected.emit(self.active_media.info.id,'toggle')
            elif self.state and len(self.state.tracks)>1 and y>=self.media_top() and event.modifiers()==Qt.NoModifier:
                other=next(track for track in self.state.tracks if track.info.id!=self.active_media.info.id)
                self.active_media_id=other.info.id
                self.mediaTrackSelected.emit(other.info.id,'replace')
                self.update()
            event.accept()
            return True
        if y<self.ruler_y() and x>=self.track_left()-30 and self.state and self.state.length:
            marker=y<self.marker_lane_height
            if self.can_add_at_cursor(marker):
                if marker: self.markerAdded.emit(self.state.position)
                else: self.drawingKeyAdded.emit()
            event.accept()
            return True
        track=self.media_row_at(y)
        if track is None: return False
        if x>=self.track_left()-30 and event.modifiers()==Qt.NoModifier:
            self.mediaAudioEnabled.emit(track.info.id,not track.info.audio_enabled)
        elif x<23 and event.modifiers()==Qt.NoModifier:
            self.mediaAudioExpanded.emit(track.info.id,not track.info.audio_expanded)
        else:
            self.active_media_id=track.info.id
            self.mediaTrackSelected.emit(track.info.id,'toggle' if event.modifiers()&Qt.KeyboardModifier.ControlModifier else 'replace')
            self.media_title_drag=(track.info.id,event.position().y())
        event.accept()
        return True

    def toggle_media_selection(self,event):
        if event.button()!=Qt.LeftButton or event.modifiers()!=Qt.ControlModifier: return False
        if self.simple:
            track=self.active_media if self.state and self.simple_track_rect().contains(event.position()) else None
        else: track=self.media_row_at(event.position().y())
        if track is None: return False
        self.mediaTrackSelected.emit(track.info.id,'toggle')
        event.accept(); return True

    def begin_cross_drag(self,event):
        self.cross_origin=None; self.cross_target=None; self.cross_copy=False
        if self.state.second_track is None or not event.modifiers() & Qt.AltModifier: return
        if self.simple and not self.simple_track_rect().contains(event.position()): return
        target=self.context_target(event.position().x(),event.position().y(),False)
        if target is None: return
        a,b,kind=target
        from model import locate
        if all(locate(segments,a)[0] is None for segments in (self.active_media.segments,self.active_media.audio)): return
        self.cross_origin=(self.active_media.info.id,a,b)

    def update_cross_drag(self,event,x):
        origin=getattr(self,'cross_origin',None)
        if origin is None or self.gesture not in ('move','copy','transfer'): return False
        if not event.modifiers() & Qt.AltModifier:
            self.clear_clip_drag()
            return True
        pos=event.position()
        if self.simple:
            in_title=(0<=pos.x()<self.track_left() and self.simple_track_rect().top()<=pos.y()<self.height())
            target=next((t for t in self.state.tracks if t.info.id!=origin[0]),None) if in_title else None
        else:
            target=self.media_row_at(pos.y()) if self.rect().contains(pos.toPoint()) else None
        if target is None or target.info.id==origin[0]:
            self.cross_target=None
            if self.gesture=='transfer': self.update(); return True
            return False
        self.cross_target=target.info.id
        if self.gesture!='transfer':
            self.cross_copy=self.gesture=='copy'
            self.cross_origin=(origin[0],self.move_span[0],self.move_span[1])
            self.gesture='transfer'; self.finish_range_drag()
        if self.simple: x=self.x_for(origin[1])+self.grab_offset
        frame=max(0,min(self.state.length,round(self.raw_frame(x-self.grab_offset)))); at=0
        for segment in target.segments:
            end=at+segment.length
            if at<frame<end and segment.media is not None:
                frame=at if frame-at<=end-frame else end; break
            at=end
        self.snap_drop(frame,x); return True

    def release_media_title(self,event):
        drag=getattr(self,'media_title_drag',None)
        if drag is None: return False
        self.media_title_drag=None
        target=self.media_row_at(event.position().y())
        if target and target.info.id!=drag[0] and abs(event.position().y()-drag[1])>=5:
            self.mediaTrackReordered.emit(drag[0],1 if event.position().y()>drag[1] else -1)
        event.accept()
        return True

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
