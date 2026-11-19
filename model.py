# SPDX-License-Identifier: GPL-3.0-only
"""Non-destructive frame edit model. No GUI or decoder dependency."""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from fractions import Fraction
from functools import cached_property
from bisect import bisect_left,bisect_right
import json
import uuid
from pathlib import Path
from track_edits import selected_tracks
from drawing import DrawingKey, load_keys, slice_keys, remove_key_range, insert_keys, relocate_keys, resize_key

RATE = 48000
CHANNELS = 2
SAMPLE_BYTES = 4

def sample_at(frame: int, fps: Fraction) -> int:
    value = Fraction(frame * RATE, 1) / fps
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)

@dataclass(frozen=True)
class Segment:
    media: str | None
    start: int
    end: int
    muted: bool = False
    cut_before: bool = False
    crop: tuple = (0.,0.,1.,1.)
    placement: tuple = (0.,0.,1.,1.)
    rotation: float = 0.
    def __post_init__(self):
        import math
        if not isinstance(self.rotation,(int,float)) or not math.isfinite(self.rotation) or not -180<=self.rotation<=180: raise ValueError('Rotation de clip invalide.')
        for key in ('crop','placement'):
            value=tuple(getattr(self,key))
            if len(value)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in value): raise ValueError('Cadrage invalide.')
            x,y,w,h=value
            if key=='crop':
                if x<0 or y<0 or w<.001 or h<.001 or x+w>1.000001 or y+h>1.000001: raise ValueError('Recadrage hors image.')
            elif not (-3<=x<=3 and -3<=y<=3 and .001<=w<=4 and .001<=h<=4): raise ValueError('Dimensions invalides.')
            object.__setattr__(self,key,value)
    @property
    def length(self): return self.end - self.start


@dataclass(frozen=True)
class TrackInfo:
    id: str = 'media-1'
    name: str = 'Piste 1'
    audio_expanded: bool = False
    audio_enabled: bool = True


@dataclass(frozen=True)
class MediaTrack:
    info: TrackInfo
    segments: tuple[Segment, ...] = ()
    audio_segments: tuple[Segment, ...] | None = None
    exposure: float = 0.
    flip_h: bool = False
    flip_v: bool = False

    @property
    def audio(self): return self.segments if self.audio_segments is None else self.audio_segments

    @property
    def audible(self): return self.audio if self.info.audio_enabled else tuple(replace(s,muted=True) for s in self.audio)

    @property
    def length(self): return sum(s.length for s in self.segments)


@dataclass(frozen=True)
class State:
    segments: tuple[Segment, ...] = ()
    exposure: float = 0.0
    position: int = 0
    selection: tuple[int, int] | None = None
    loop_range: tuple[int, int] | None = None
    flip_h: bool = False
    flip_v: bool = False
    audio_segments: tuple[Segment, ...] | None = None
    drawings: tuple[DrawingKey, ...] = ()
    drawings_linked: bool = True
    frame_markers: tuple[int, ...] = ()
    track_info: TrackInfo = TrackInfo()
    second_track: MediaTrack | None = None
    @property
    def audio(self): return self.segments if self.audio_segments is None else self.audio_segments
    @cached_property
    def length(self): return max(track.length for track in self.tracks)

    @property
    def tracks(self):
        first=MediaTrack(self.track_info,self.segments,self.audio_segments,self.exposure,self.flip_h,self.flip_v)
        return (first,self.second_track) if self.second_track is not None else (first,)

    @property
    def all_segments(self): return tuple(seg for track in self.tracks for seg in track.segments+track.audio)


def with_tracks(state,tracks):
    first=tracks[0]
    return replace(state,segments=first.segments,audio_segments=first.audio_segments,
                   exposure=first.exposure,flip_h=first.flip_h,flip_v=first.flip_v,
                   track_info=first.info,second_track=tracks[1] if len(tracks)>1 else None)


def track_state(state,track):
    return with_tracks(state,(track,))


def slice_segments(segments, start, end):
    result, at = [], 0
    for seg in segments:
        left, right = max(start, at), min(end, at + seg.length)
        if right > left:
            result.append(replace(seg,start=seg.start + left-at,end=seg.start + right-at))
        at += seg.length
    return tuple(result)


def compact(segments):
    out = []
    for seg in segments:
        if seg.length <= 0: continue
        if out and out[-1].media is None and seg.media is None:
            out[-1] = Segment(None,0,out[-1].length+seg.length)
        elif out and not seg.cut_before and out[-1].muted==seg.muted and out[-1].crop==seg.crop and out[-1].placement==seg.placement and out[-1].rotation==seg.rotation and out[-1].media == seg.media and out[-1].end == seg.start:
            out[-1] = replace(out[-1], end=seg.end)
        else: out.append(seg)
    return tuple(out)


def locate(segments, index):
    at = 0
    for seg in segments:
        if at <= index < at + seg.length:
            return seg.media, seg.start + index - at
        at += seg.length
    raise IndexError(index)


def empty_duration(segments,frame):
    at=0; length=0
    for seg in segments:
        end=at+seg.length
        if end>frame:
            if seg.media is not None: break
            length+=end-max(at,frame)
        at=end
    return length

class Document:
    def __init__(self, fps=Fraction(24)):
        self.drawing_transfer_id = uuid.uuid4().hex
        self.fps = Fraction(fps)
        self.state = State()
        self.media = {}
        self.clipboard = (); self.audio_clipboard = (); self.drawing_clipboard = (); self.drawing_clipboard_length = 0
        self.track_clipboards = {}
        self.selected_track_ids = ('media-1',)
        self.active_track_id = 'media-1'
        self.undo_stack = []
        self.redo_stack = []
        self.review = {}
        self.saved_signature = self.signature()
        self.project_path = None

    def signature(self):
        return (self.state.tracks, self.fps, self.state.drawings, self.state.drawings_linked, self.state.frame_markers, json.dumps(self.review,sort_keys=True))

    def normalize_tracks(self):
        ids=tuple(t.info.id for t in self.state.tracks)
        self.selected_track_ids=ids if len(ids)==1 else tuple(i for i in self.selected_track_ids if i in ids)
        if self.active_track_id not in ids: self.active_track_id=next(iter(self.selected_track_ids),ids[0])

    @property
    def active_track(self):
        self.normalize_tracks()
        return next(t for t in self.state.tracks if t.info.id==self.active_track_id)

    def editable_tracks(self):
        self.normalize_tracks()
        return tuple(t for t in self.state.tracks if t.info.id in self.selected_track_ids)

    def select_track(self,identity,extend=False):
        if identity not in {t.info.id for t in self.state.tracks}: return
        chosen=set(self.selected_track_ids) if extend else set()
        if extend and identity in chosen: chosen.remove(identity)
        else: chosen.add(identity)
        self.selected_track_ids=tuple(t.info.id for t in self.state.tracks if t.info.id in chosen)
        self.active_track_id=identity if identity in chosen or not chosen else self.selected_track_ids[0]

    def clipboard_state(self):
        return self.clipboard,self.audio_clipboard,self.drawing_clipboard,self.drawing_clipboard_length

    def add_media_track(self):
        if self.state.second_track is not None: return False
        identity=uuid.uuid4().hex
        name=next(name for name in ('Piste 1','Piste 2') if name not in {t.info.name for t in self.state.tracks})
        changed=self.commit('Ajouter une piste média',replace(self.state,second_track=MediaTrack(TrackInfo(identity,name))))
        self.select_track(identity)
        return changed

    def remove_media_track(self,identity):
        tracks=tuple(t for t in self.state.tracks if t.info.id!=identity)
        if len(tracks)==len(self.state.tracks): return False
        if not tracks: tracks=(MediaTrack(TrackInfo()),)
        changed=self.commit('Supprimer la piste média',with_tracks(self.state,tracks))
        self.normalize_tracks()
        return changed

    def reorder_media_track(self,identity,direction):
        tracks=list(self.state.tracks)
        index=next((i for i,t in enumerate(tracks) if t.info.id==identity),-1)
        destination=index+int(direction)
        if index<0 or not 0<=destination<len(tracks): return False
        tracks.insert(destination,tracks.pop(index))
        return self.commit('Réordonner les pistes média',with_tracks(self.state,tracks))

    def expand_track_audio(self,identity,expanded):
        return self.commit('Afficher la bande audio' if expanded else 'Replier la bande audio',with_tracks(self.state,
            tuple(replace(t,info=replace(t.info,audio_expanded=bool(expanded))) if t.info.id==identity else t for t in self.state.tracks)))

    def enable_track_audio(self,identity,enabled):
        return self.commit('Activer l’audio de la piste' if enabled else 'Désactiver l’audio de la piste',with_tracks(self.state,
            tuple(replace(t,info=replace(t.info,audio_enabled=bool(enabled))) if t.info.id==identity else t for t in self.state.tracks)))

    def transfer_media(self,source_id,target_id,start,end,destination,copy=False):
        tracks={t.info.id:t for t in self.state.tracks}
        if source_id==target_id or not {source_id,target_id}<=set(self.selected_track_ids): return False
        source,target=tracks[source_id],tracks[target_id]
        start,end,destination=int(start),int(end),int(destination)
        if not 0<=start<end<=source.length or not 0<=destination<=self.state.length: return False
        size=end-start
        def pad(segments):
            missing=max(0,destination-target.length)
            return segments+((Segment(None,0,missing),) if missing else ())
        video,audio=pad(target.segments),pad(target.audio)
        filled=min(size,empty_duration(video,destination),empty_duration(audio,destination))
        def insert(segments,block):
            block=(replace(block[0],cut_before=True),)+block[1:]
            right=slice_segments(segments,destination+filled,max(destination,target.length))
            if right: right=(replace(right[0],cut_before=True),)+right[1:]
            return compact(slice_segments(segments,0,destination)+block+right)
        tracks[target_id]=replace(target,segments=insert(video,slice_segments(source.segments,start,end)),
                                 audio_segments=insert(audio,slice_segments(source.audio,start,end)))
        if not copy:
            def remove(segments): return compact(slice_segments(segments,0,start)+slice_segments(segments,end,source.length))
            tracks[source_id]=replace(source,segments=remove(source.segments),audio_segments=remove(source.audio))
        result=with_tracks(self.state,tuple(tracks[t.info.id] for t in self.state.tracks))
        self.active_track_id=target_id
        return self.commit('Copier vers une autre piste' if copy else 'Déplacer vers une autre piste',replace(result,position=destination,selection=(destination,destination+size),loop_range=None))

    def set_track_effect(self,label,**fields):
        ids={t.info.id for t in self.editable_tracks()}
        return self.commit(label,with_tracks(self.state,tuple(replace(t,**fields) if t.info.id in ids else t for t in self.state.tracks)))

    def set_track_segments(self,identity,segments,label):
        return self.commit(label,with_tracks(self.state,tuple(replace(t,segments=segments,audio_segments=t.audio)
            if t.info.id==identity else t for t in self.state.tracks)))

    @property
    def dirty(self): return self.signature() != self.saved_signature

    def commit(self, label, new):
        new=replace(new,frame_markers=tuple(sorted(set(f for f in new.frame_markers if 0<=f<new.length))))
        if new.position>new.length: new=replace(new,position=max(0,new.length-1))
        if new.selection and new.selection[1]>new.length:
            a,b=new.selection; new=replace(new,selection=(a,new.length) if a<new.length else None)
        if new.loop_range and new.loop_range[1]>new.length: new=replace(new,loop_range=None)
        if new == self.state: return False
        self.undo_stack.append((label, self.state, new))
        self.redo_stack.clear()
        self.state = new
        return True

    def undo(self):
        if not self.undo_stack: return False
        item = self.undo_stack.pop()
        self.redo_stack.append(item)
        self.state = item[1]
        return True

    def redo(self):
        if not self.redo_stack: return False
        item = self.redo_stack.pop()
        self.undo_stack.append(item)
        self.state = item[2]
        return True

    def select(self, start, end):
        n = self.state.length
        start, end = max(0, min(start, n)), max(0, min(end, n))
        self.state = replace(self.state, selection=(min(start,end),max(start,end)) if start != end else None)

    def selected(self):
        if self.state.selection: return self.state.selection
        return (self.state.position, min(self.state.length, self.state.position+1))

    @selected_tracks
    def copy(self, include_audio=True):
        a,b = self.selected()
        self.drawing_clipboard = slice_keys(self.state.drawings,a,b,-a) if self.state.drawings_linked else ()
        self.drawing_clipboard_length = b-a
        self.clipboard = slice_segments(self.state.segments,a,b)
        self.audio_clipboard = slice_segments(self.state.audio,a,b) if include_audio else (Segment(None,0,b-a),) if b>a else ()
        return sum(s.length for s in self.clipboard)

    @selected_tracks
    def cut(self, include_audio=True):
        a,b = self.selected()
        if b <= a: return 0  # Preserve the clipboard at the end of an empty range.
        count = self.copy(include_audio)
        self.delete('Couper les images')
        return count

    @selected_tracks
    def delete(self, label='Supprimer les images'):
        a,b = self.selected()
        if b <= a: return False
        segs = compact(slice_segments(self.state.segments,0,a)+slice_segments(self.state.segments,b,self.state.length))
        length = sum(s.length for s in segs)
        return self.commit(label,replace(self.state,drawings=remove_key_range(self.state.drawings,a,b,True) if self.state.drawings_linked else self.state.drawings,segments=segs,audio_segments=compact(slice_segments(self.state.audio,0,a)+slice_segments(self.state.audio,b,self.state.length)),position=min(a,max(0,length-1)),selection=None,loop_range=None))

    @selected_tracks
    def paste(self, include_audio=True):
        if not self.clipboard: return False
        at = max(0,min(self.state.position,self.state.length))
        size = sum(s.length for s in self.clipboard)
        segs = compact(slice_segments(self.state.segments,0,at)+self.clipboard+slice_segments(self.state.segments,at,self.state.length))
        return self.commit('Coller les images',replace(self.state,drawings=insert_keys(self.state.drawings,at,size,self.drawing_clipboard) if self.state.drawings_linked else self.state.drawings,segments=segs,audio_segments=compact(slice_segments(self.state.audio,0,at)+((self.audio_clipboard or self.clipboard) if include_audio else (Segment(None,0,size),))+slice_segments(self.state.audio,at,self.state.length)),selection=(at,at+size),loop_range=None))

    @selected_tracks
    def append_media(self, items):
        if not items: return False
        for m in items:
            if Fraction(m['fps']) != self.fps: raise ValueError('Cadence incompatible.')
        self.media.update({m['id']:m for m in items})
        at=self.state.length
        segments=self.state.segments+tuple(Segment(m['id'] if m.get('has_video',True) else None,0,m['frames']) for m in items)
        return self.commit('Ajouter des médias',replace(self.state,segments=segments,audio_segments=self.state.audio+tuple(Segment(m['id'],0,m['frames']) for m in items),position=at,selection=None,loop_range=None))

    @selected_tracks
    def duplicate_range(self,start,end,destination=None):
        n=self.state.length
        if not 0<=start<end<=n: return False
        at=end if destination is None else self.snap_destination(max(0,min(int(destination),n)))
        def insert(segs):
            block=slice_segments(segs,start,end); right=slice_segments(segs,at,n)
            block=(replace(block[0],cut_before=True),)+block[1:]
            if right: right=(replace(right[0],cut_before=True),)+right[1:]
            return compact(slice_segments(segs,0,at)+block+right)
        return self.commit('Dupliquer le média',replace(self.state,drawings=insert_keys(self.state.drawings,at,end-start,slice_keys(self.state.drawings,start,end,-start)) if self.state.drawings_linked else self.state.drawings,segments=insert(self.state.segments),audio_segments=insert(self.state.audio),position=at,selection=(at,at+end-start),loop_range=None))

    @selected_tracks
    def move_range(self, start, end, destination, track='linked', leave_gap=False):
        n=self.state.length
        if track not in ('linked','video','audio'): raise ValueError('Piste invalide')
        start,end,destination=int(start),int(end),int(destination)
        if not 0<=start<end<=n or not 0<=destination<=n: return False
        destination=self.snap_destination(destination,track)
        if start<=destination<=end: return False
        at=destination-(end-start) if destination>end and not leave_gap else destination
        def remove(segments):
            return compact(slice_segments(segments,0,start)+((Segment(None,0,end-start),) if leave_gap else ())+slice_segments(segments,end,n))
        video_rest=remove(self.state.segments); audio_rest=remove(self.state.audio)
        targets=[video_rest,audio_rest] if track=='linked' else [audio_rest if track=='audio' else video_rest]
        filled=min(end-start,*(empty_duration(segments,at) for segments in targets))
        def move(segments,rest):
            block=slice_segments(segments,start,end)
            return compact(slice_segments(rest,0,at)+block+slice_segments(rest,at+filled,n if leave_gap else n-(end-start)))
        video=move(self.state.segments,video_rest) if track!='audio' else self.state.segments
        audio=move(self.state.audio,audio_rest) if track!='video' else self.state.audio
        length=max(sum(s.length for s in video),sum(s.length for s in audio))
        def pad(segs):
            missing=length-sum(s.length for s in segs)
            return compact(segs+((Segment(None,0,missing),) if missing else ()))
        video,audio=pad(video),pad(audio)
        drawings=self.state.drawings
        if self.state.drawings_linked and track!='audio':
            block=slice_keys(drawings,start,end,at-start)
            rest=remove_key_range(drawings,start,end,not leave_gap)
            if filled:
                from drawing import overlay_keys
                drawings=overlay_keys(insert_keys(rest,at+filled,end-start-filled),block)
            else: drawings=insert_keys(rest,at,end-start,slice_keys(drawings,start,end,-start))
        return self.commit('Déplacer '+{'linked':'vidéo et audio','video':'la vidéo','audio':'l’audio'}[track],replace(self.state,drawings=drawings,segments=video,audio_segments=audio,position=at,selection=None,loop_range=None))

    def snap_destination(self,frame,track='video'):
        frame=max(0,min(int(frame),self.state.length)); at=0
        active=self.active_track
        for seg in (active.audio if track=='audio' else active.segments):
            end=at+seg.length
            if at<frame<end and seg.media is not None:
                return at if frame-at<=end-frame else end
            at=end
        return frame

    @selected_tracks
    def split_at(self,frame,track='linked'):
        if not 0<frame<self.state.length: return False
        def split(segs):
            out=[]; at=0
            for seg in segs:
                if at<frame<at+seg.length:
                    offset=frame-at; out.extend((replace(seg,end=seg.start+offset),replace(seg,start=seg.start+offset,cut_before=True)))
                else: out.append(seg)
                at+=seg.length
            return tuple(out)
        return self.commit('Scinder',replace(self.state,segments=split(self.state.segments) if track!='audio' else self.state.segments,audio_segments=split(self.state.audio) if track!='video' else self.state.audio))

    @selected_tracks
    def mute_range(self,start,end,track):
        if track not in ('video','audio') or not 0<=start<end<=self.state.length: return False
        segs=self.state.segments if track=='video' else self.state.audio
        middle=slice_segments(segs,start,end); value=not all(s.muted for s in middle)
        changed=compact(slice_segments(segs,0,start)+tuple(replace(s,muted=value) for s in middle)+slice_segments(segs,end,self.state.length))
        fields={'segments':changed,'audio_segments':self.state.audio} if track=='video' else {'audio_segments':changed}
        return self.commit('Mute '+track,replace(self.state,**fields))

    @selected_tracks
    def delete_track_range(self,start,end,track):
        if track not in ('video','audio') or not 0<=start<end<=self.state.length: return False
        segs=self.state.segments if track=='video' else self.state.audio
        changed=compact(slice_segments(segs,0,start)+(Segment(None,0,end-start),)+slice_segments(segs,end,self.state.length))
        fields={'segments':changed,'audio_segments':self.state.audio} if track=='video' else {'audio_segments':changed}
        return self.commit('Supprimer '+track,replace(self.state,drawings=remove_key_range(self.state.drawings,start,end) if track=='video' and self.state.drawings_linked else self.state.drawings,**fields,position=min(start,self.state.length-1),selection=None,loop_range=None))

    @selected_tracks
    def delete_ranges(self,ranges):
        ranges=sorted((max(0,a),min(self.state.length,b)) for a,b in ranges if b>a)
        if not ranges: return False
        def keep(segs):
            out=(); at=0
            for a,b in ranges:
                if a>at: out+=slice_segments(segs,at,a)
                at=max(at,b)
            return compact(out+slice_segments(segs,at,self.state.length))
        video=keep(self.state.segments); audio=keep(self.state.audio); length=sum(s.length for s in video)
        drawings=self.state.drawings
        if self.state.drawings_linked:
            merged=[]
            for a,b in ranges:
                if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                else: merged.append((a,b))
            for a,b in reversed(merged): drawings=remove_key_range(drawings,a,b,True)
        return self.commit('Retirer la sélection du montage',replace(self.state,drawings=drawings,segments=video,audio_segments=audio,position=min(ranges[0][0],max(0,length-1)),selection=None,loop_range=None))

    def remove_media(self,key): return self.remove_media_keys([key])
    @selected_tracks
    def remove_media_keys(self,keys):
        keys=set(keys)
        drawings=self.state.drawings; at=0; removed=[]
        for seg in self.state.segments:
            if seg.media in keys: removed.append((at,at+seg.length))
            at+=seg.length
        if self.state.drawings_linked:
            for a,b in reversed(removed): drawings=remove_key_range(drawings,a,b,True)
        video=tuple(s for s in self.state.segments if s.media not in keys)
        audio=tuple(s for s in self.state.audio if s.media not in keys)
        n=max(sum(s.length for s in video),sum(s.length for s in audio))
        def pad(segs):
            missing=n-sum(s.length for s in segs)
            return segs+((Segment(None,0,missing),) if missing else ())
        return self.commit('Retirer le média du montage',replace(self.state,drawings=drawings,segments=pad(video),audio_segments=pad(audio),position=min(self.state.position,max(0,n-1)),selection=None,loop_range=None))

    @selected_tracks
    def insert_gap(self,frames):
        frames=int(frames)
        if frames<=0: return False
        at=self.snap_destination(self.state.position); n=self.state.length
        def insert(segs): return compact(slice_segments(segs,0,at)+(Segment(None,0,frames),)+slice_segments(segs,at,n))
        return self.commit('Insérer un vide',replace(self.state,drawings=insert_keys(self.state.drawings,at,frames) if self.state.drawings_linked else self.state.drawings,segments=insert(self.state.segments),audio_segments=insert(self.state.audio),position=at,selection=(at,at+frames),loop_range=None))

    def move_drawings(self,start,end,destination):
        keys=relocate_keys(self.state.drawings,start,end,destination,self.state.length)
        if keys==self.state.drawings: return False
        at=max(0,min(destination,self.state.length-(end-start)))
        selection=(at,at+end-start) if self.state.selection else None
        return self.commit('Déplacer les clés de dessin',replace(self.state,drawings=keys,position=at,selection=selection))

    def resize_drawing(self,start,new_start,new_end):
        keys=resize_key(self.state.drawings,start,new_start,new_end,self.state.length)
        return self.commit('Redimensionner la plage de dessin',replace(self.state,drawings=keys))

    def delete_drawings(self,start,end):
        return self.commit('Supprimer la plage de dessin',replace(self.state,drawings=remove_key_range(self.state.drawings,start,end)))

    def copy_drawings(self,start,end):
        if not 0<=start<end<=self.state.length: return False
        keys=slice_keys(self.state.drawings,start,end,-start)
        if not keys: return False
        self.drawing_clipboard=keys; self.drawing_clipboard_length=end-start
        return True

    def cut_drawings(self,start,end):
        if not self.copy_drawings(start,end): return False
        return self.commit('Couper les dessins',replace(self.state,drawings=remove_key_range(self.state.drawings,start,end)))

    def paste_drawings(self,at):
        if not self.drawing_clipboard or not 0<=at<=self.state.length-self.drawing_clipboard_length: return False
        from drawing import put_key
        keys=self.state.drawings
        for key in self.drawing_clipboard: keys=put_key(keys,replace(key,start=key.start+at,end=key.end+at))
        return self.commit('Coller les dessins',replace(self.state,drawings=keys,position=at,selection=(at,at+self.drawing_clipboard_length),loop_range=None))

    @selected_tracks
    def exposure(self, value):
        return self.commit('Régler l’exposition',replace(self.state,exposure=round(float(value),2)))

    def to_data(self, all_media=False):
        return {'format':'cadence-studio','version':self.format_version(),'fps':str(self.fps),'media':[m for k,m in self.media.items() if all_media or any(s.media==k for s in self.state.all_segments)],'state':asdict(self.state),'comparison':self.review,'drawing_transfer_id':self.drawing_transfer_id}

    def format_version(self):
        if self.state.second_track is not None or not self.state.track_info.audio_enabled or self.review.get('reference_track'): return 16
        used={s.media for s in self.state.segments+self.state.audio}
        return 15 if len(self.review.get('references',[]))>1 else 14 if self.review.get('reference_cadence') or any(m.get('cadence') for k,m in self.media.items() if k in used) else 13 if any(m.get('has_video') is False for m in self.media.values()) else 12 if self.state.frame_markers else 11

    def save(self, path):
        data = self.to_data()
        target = Path(path)
        tmp = target.with_suffix(target.suffix+'.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(target)
        self.project_path = str(target)
        self.saved_signature = self.signature()

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls.from_data(data,str(path))

    @classmethod
    def from_data(cls, data, project_path=None):
        if data.get('format') != 'cadence-studio' or data.get('version') not in range(1,17):
            raise ValueError('Ce fichier n’est pas un projet Cadence compatible.')
        doc = cls(Fraction(data['fps']))
        identity=data.get('drawing_transfer_id')
        if isinstance(identity,str) and len(identity)==32:
            try: doc.drawing_transfer_id=uuid.UUID(identity).hex
            except ValueError: pass
        doc.review = data.get('comparison',{}) if isinstance(data.get('comparison',{}),dict) else {}
        references=doc.review.get('references',[])
        if not isinstance(references,list) or any(not isinstance(entry,dict) or not isinstance(entry.get('path'),str) for entry in references):
            raise ValueError('Liste de références invalide.')
        if not 1 <= doc.fps <= 240: raise ValueError('Cadence de projet non prise en charge.')
        doc.media = {m['id']:m for m in data['media']}
        from cadence_change import settings
        for media in doc.media.values():
            if 'cadence' in media: media['cadence']=settings(media['cadence'])
        st = data['state']
        segs = tuple(Segment(**s) for s in st['segments'])
        audio=tuple(Segment(**s) for s in st['audio_segments']) if st.get('audio_segments') is not None else None
        if audio is not None and sum(s.length for s in audio)!=sum(s.length for s in segs): raise ValueError('Durées audio et vidéo incohérentes.')
        def info(value,default):
            if value is None: return default
            if not isinstance(value,dict) or set(value)-{'id','name','audio_expanded','audio_enabled'}: raise ValueError('Piste média invalide.')
            result=TrackInfo(**value)
            if not isinstance(result.id,str) or not 1<=len(result.id)<=64 or not isinstance(result.name,str) or not 1<=len(result.name)<=80 or type(result.audio_expanded) is not bool or type(result.audio_enabled) is not bool:
                raise ValueError('Piste média invalide.')
            if result.name in ('Média 1','Média 2'): result=replace(result,name=result.name.replace('Média','Piste'))
            return result
        first_info=info(st.get('track_info'),TrackInfo())
        second=None
        if st.get('second_track') is not None:
            value=st['second_track']
            if not isinstance(value,dict) or set(value)-{'info','segments','audio_segments','exposure','flip_h','flip_v'}: raise ValueError('Seconde piste média invalide.')
            second=MediaTrack(info(value.get('info'),TrackInfo('media-2','Piste 2')),
                tuple(Segment(**s) for s in value['segments']),
                tuple(Segment(**s) for s in value['audio_segments']) if value.get('audio_segments') is not None else None,
                float(value.get('exposure',0)),bool(value.get('flip_h',False)),bool(value.get('flip_v',False)))
            if second.info.id==first_info.id or not -10<=second.exposure<=10 or sum(s.length for s in second.audio)!=second.length:
                raise ValueError('Seconde piste média invalide.')
        for seg in segs+(audio or ())+((second.segments+second.audio) if second else ()):
            if seg.media is None:
                if not 0<=seg.start<seg.end: raise ValueError('Vide invalide.')
                continue
            if seg.media not in doc.media or not 0 <= seg.start < seg.end <= doc.media[seg.media]['frames']:
                raise ValueError('Plage de média invalide dans le projet.')
        length = max(sum(s.length for s in segs),second.length if second else 0)
        sel = st.get('selection')
        if sel and not 0 <= sel[0] < sel[1] <= length: sel = None
        loop = st.get('loop_range')
        if loop and not 0 <= loop[0] < loop[1] <= length: loop = None
        ev = float(st.get('exposure',0))
        if not -10 <= ev <= 10: raise ValueError('Exposition invalide.')
        markers=st.get('frame_markers',[])
        if not isinstance(markers,(list,tuple)) or any(type(f) is not int or not 0<=f<length for f in markers): raise ValueError('Marqueurs invalides.')
        doc.state = State(segs,ev,max(0,min(int(st.get('position',0)),length)),tuple(sel) if sel else None,tuple(loop) if loop else None,bool(st.get("flip_h",False)),bool(st.get("flip_v",False)),audio,load_keys(st.get('drawings',[])),bool(st.get('drawings_linked',True)),tuple(sorted(set(markers))),first_info,second)
        doc.normalize_tracks()
        doc.project_path = project_path
        doc.saved_signature = doc.signature()
        return doc


class TimelinePCM:
    """Exact global sample boundaries; rescale sub-sample rounding at each edit."""
    def __init__(self, segments, media, fps):
        import numpy as np
        self.np = np
        self.fps = fps
        self.maps = {}
        self.regions = []
        at = 0
        for seg in segments:
            if seg.media is None or seg.muted:
                at+=seg.length
                continue
            if seg.media not in self.maps:
                path = media[seg.media]['audio']
                self.maps[seg.media] = np.memmap(path,dtype='<i2',mode='r').reshape(-1,2)
            a,b = sample_at(at,fps),sample_at(at+seg.length,fps)
            sa,sb = sample_at(seg.start,fps),sample_at(seg.end,fps)
            self.regions.append((a,b,seg.media,sa,sb))
            at += seg.length
        self.samples = sample_at(at,fps)
        self.starts = tuple(region[0] for region in self.regions)
        self.ends = tuple(region[1] for region in self.regions)

    def read(self,start,count):
        np = self.np
        count = max(0,min(count,self.samples-start))
        out = np.zeros((count,2),dtype='<i2')
        first=bisect_right(self.ends,start); last=bisect_left(self.starts,start+count)
        for index in range(first,last):
            a,b,key,sa,sb=self.regions[index]
            l,r = max(a,start),min(b,start+count)
            if r <= l: continue
            # Source/destination spans differ by at most one rounding sample.
            indices = sa + ((np.arange(l,r,dtype=np.int64)-a)*(sb-sa)//max(1,b-a))
            data = self.maps[key]
            valid = (indices >= 0) & (indices < len(data))
            out[l-start:r-start][valid] = data[indices[valid]]
        return out.tobytes()

    def close(self):
        for data in self.maps.values():
            mmap = getattr(data,'_mmap',None)
            if mmap: mmap.close()
        self.maps.clear()
