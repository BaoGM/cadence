# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from PySide6.QtCore import QSignalBlocker
from ui_text import tr


class MediaTrackController:
    def init_media_tracks(self):
        timeline=self.timeline
        timeline.mediaTrackSelected.connect(self.select_media_track)
        timeline.mediaTrackAdded.connect(self.add_media_track)
        timeline.mediaTrackRemoved.connect(lambda identity:self.edit_track_structure(self.doc.remove_media_track,identity))
        timeline.mediaTrackReordered.connect(lambda identity,direction:self.edit_track_structure(self.doc.reorder_media_track,identity,direction))
        timeline.mediaAudioExpanded.connect(self.expand_media_audio)
        timeline.mediaAudioEnabled.connect(lambda identity,enabled:self.edit_track_structure(self.doc.enable_track_audio,identity,enabled))
        timeline.mediaTransferred.connect(lambda source,target,a,b,at,copy:self.edit_track_structure(self.doc.transfer_media,source,target,a,b,at,copy))
        timeline.mediaReferenceRequested.connect(self.use_track_reference)
        from studio_chrome import control
        self.add_track_button=control('Ajouter une seconde piste média sous la première.', 'plus', 'Piste média')
        self.add_track_button.clicked.connect(self.add_media_track)
        self.header_scroll.widget().layout().addWidget(self.add_track_button)
        from volume_shortcut import VolumeShortcut
        self.volume_shortcut=VolumeShortcut(self)

    def select_media_track(self,identity,mode='replace'):
        if self.job: return
        self.commit_exposure()
        if self.clip_tools.mode: self.clip_tools.commit()
        if mode=='activate' and identity in self.doc.selected_track_ids: self.doc.active_track_id=identity
        else: self.doc.select_track(identity,mode=='toggle')
        self.exp_pending=self.doc.active_track.exposure
        self.timeline.selection_track='video'
        self.refresh(); self.request_frame()

    def add_media_track(self):
        if self.job: return
        if hasattr(self,'workspaces'): self.workspaces.switch('edit')
        self.edit_track_structure(self.doc.add_media_track)

    def edit_track_structure(self,operation,*args):
        if self.job: return
        self.pause(); self.commit_exposure(); self.clip_tools.commit()
        if operation(*args):
            self.exp_pending=self.doc.active_track.exposure
            self.refresh(); self.request_frame(); self.sync_timeline_scroll()

    def expand_media_audio(self,identity,expanded):
        self.doc.expand_track_audio(identity,expanded)
        self.refresh(); self.sync_timeline_scroll()

    def refresh_media_tracks(self):
        self.doc.normalize_tracks()
        self.timeline.active_media_id=self.doc.active_track_id
        self.timeline.selected_media_ids=self.doc.selected_track_ids
        self.add_track_button.setEnabled(self.doc.state.second_track is None and not self.job)

    def geometry_selected(self,segment,label):
        from model import with_tracks
        tracks=[]
        ids=set(self.doc.selected_track_ids)
        for track in self.doc.state.tracks:
            segments=list(track.segments); at=0
            if track.info.id in ids:
                for index,item in enumerate(segments):
                    if at<=self.doc.state.position<at+item.length:
                        if item.media is not None:
                            segments[index]=replace(item,crop=segment.crop,placement=segment.placement,rotation=segment.rotation)
                        break
                    at+=item.length
                track=replace(track,segments=tuple(segments),audio_segments=track.audio)
            tracks.append(track)
        return self.doc.commit(label,with_tracks(self.doc.state,tuple(tracks)))
