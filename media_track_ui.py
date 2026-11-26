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
        from clip_trim import trim_media
        timeline.mediaTrimmed.connect(lambda *args:self.edit_track_structure(trim_media,self.doc,*args,follow_edge=True))
        timeline.trimPreviewChanged.connect(self.preview_trim_frame)
        timeline.mediaEdgeFocused.connect(self.seek)
        timeline.mediaReversed.connect(lambda *args:self.edit_track_structure(self.doc.reverse_clip,*args))
        timeline.mediaReferenceRequested.connect(self.use_track_reference)
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

    def add_media_track(self, *, switch_to_editing=True):
        if self.job: return
        if switch_to_editing and hasattr(self,'workspaces'): self.workspaces.switch('edit')
        self.edit_track_structure(self.doc.add_media_track)

    def edit_track_structure(self,operation,*args,**options):
        if self.job: return
        self.pause(); self.commit_exposure(); self.clip_tools.commit()
        if operation(*args,**options):
            self.exp_pending=self.doc.active_track.exposure
            self.refresh(); self.request_frame(); self.sync_timeline_scroll()

    def preview_trim_frame(self, sample):
        if self.job or not self.doc.state.length: return
        drag = self.timeline.clip_trim.plan is not None
        if self.transport.running:
            if not drag: return
            self.pause()
        if sample is None:
            self.refresh_position()
            self.request_frame()
            return
        state = self.doc.state
        if not drag:
            self.doc.state = replace(state, position=sample.position)
        self.timeline.state = replace(self.doc.state, position=sample.position) if drag else self.doc.state
        self.timeline.update()
        self.viewer.position = sample.position
        self.timecode_overlay.set_frame(sample.position, max(state.length, sample.position+1), self.doc.fps)
        from composite_media import canvas_size, frame_layers
        from time_warp import video_sample
        media = self.doc.media.get(sample.segment.media)
        if media and media.get('has_video', True):
            layers = [(sample.track, sample.segment, *video_sample(media, sample.segment, sample.source))]
        else:
            layers = frame_layers(state, self.doc.media, sample.position)
        self.token += 1
        self.display_frame = sample.position
        self.prepare_reference_frame(sample.position)
        if state.second_track is None and layers:
            _, segment, media, source = layers[0]
            self.viewer.geometry_segment = segment
            self.decoder.request(self.token, media, source)
        else:
            self.decoder.request_layers(self.token, layers, canvas_size(state, self.doc.media))

    def expand_media_audio(self,identity,expanded):
        self.doc.expand_track_audio(identity,expanded)
        self.refresh(); self.sync_timeline_scroll()

    def refresh_media_tracks(self):
        self.doc.normalize_tracks()
        self.timeline.active_media_id=self.doc.active_track_id
        self.timeline.selected_media_ids=self.doc.selected_track_ids
        self.add_track_button.defaultAction().setEnabled(self.doc.state.second_track is None and not self.job)

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
