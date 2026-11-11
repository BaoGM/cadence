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
    @property
    def audio(self): return self.segments if self.audio_segments is None else self.audio_segments
    @cached_property
    def length(self): return sum(s.length for s in self.segments)


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
        self.undo_stack = []
        self.redo_stack = []
        self.review = {}
        self.saved_signature = self.signature()
        self.project_path = None

    def signature(self):
        return (self.state.segments, self.state.exposure, self.state.flip_h, self.state.flip_v, self.state.audio_segments, self.fps, self.state.drawings, self.state.drawings_linked, self.state.frame_markers, json.dumps(self.review,sort_keys=True))

    @property
    def dirty(self): return self.signature() != self.saved_signature

    def commit(self, label, new):
        new=replace(new,frame_markers=tuple(sorted(set(f for f in new.frame_markers if 0<=f<new.length))))
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

    def copy(self, include_audio=True):
        a,b = self.selected()
        self.drawing_clipboard = slice_keys(self.state.drawings,a,b,-a) if self.state.drawings_linked else ()
        self.drawing_clipboard_length = b-a
        self.clipboard = slice_segments(self.state.segments,a,b)
        self.audio_clipboard = slice_segments(self.state.audio,a,b) if include_audio else (Segment(None,0,b-a),) if b>a else ()
        return sum(s.length for s in self.clipboard)

    def cut(self, include_audio=True):
        a,b = self.selected()
        if b <= a: return 0  # Preserve the clipboard at the end of an empty range.
        count = self.copy(include_audio)
        self.delete('Couper les images')
        return count

    def delete(self, label='Supprimer les images'):
        a,b = self.selected()
        if b <= a: return False
        segs = compact(slice_segments(self.state.segments,0,a)+slice_segments(self.state.segments,b,self.state.length))
        length = sum(s.length for s in segs)
        return self.commit(label,replace(self.state,drawings=remove_key_range(self.state.drawings,a,b,True) if self.state.drawings_linked else self.state.drawings,segments=segs,audio_segments=compact(slice_segments(self.state.audio,0,a)+slice_segments(self.state.audio,b,self.state.length)),position=min(a,max(0,length-1)),selection=None,loop_range=None))

    def paste(self, include_audio=True):
        if not self.clipboard: return False
        at = max(0,min(self.state.position,self.state.length))
        size = sum(s.length for s in self.clipboard)
        segs = compact(slice_segments(self.state.segments,0,at)+self.clipboard+slice_segments(self.state.segments,at,self.state.length))
        return self.commit('Coller les images',replace(self.state,drawings=insert_keys(self.state.drawings,at,size,self.drawing_clipboard) if self.state.drawings_linked else self.state.drawings,segments=segs,audio_segments=compact(slice_segments(self.state.audio,0,at)+((self.audio_clipboard or self.clipboard) if include_audio else (Segment(None,0,size),))+slice_segments(self.state.audio,at,self.state.length)),selection=(at,at+size),loop_range=None))

    def append_media(self, items):
        if not items: return False
        for m in items:
            if Fraction(m['fps']) != self.fps: raise ValueError('Cadence incompatible.')
        self.media.update({m['id']:m for m in items})
        at=self.state.length
        segments=self.state.segments+tuple(Segment(m['id'] if m.get('has_video',True) else None,0,m['frames']) for m in items)
        return self.commit('Ajouter des médias',replace(self.state,segments=segments,audio_segments=self.state.audio+tuple(Segment(m['id'],0,m['frames']) for m in items),position=at,selection=None,loop_range=None))

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
        for seg in (self.state.audio if track=='audio' else self.state.segments):
            end=at+seg.length
            if at<frame<end and seg.media is not None:
                return at if frame-at<=end-frame else end
            at=end
        return frame

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

    def mute_range(self,start,end,track):
        if track not in ('video','audio') or not 0<=start<end<=self.state.length: return False
        segs=self.state.segments if track=='video' else self.state.audio
        middle=slice_segments(segs,start,end); value=not all(s.muted for s in middle)
        changed=compact(slice_segments(segs,0,start)+tuple(replace(s,muted=value) for s in middle)+slice_segments(segs,end,self.state.length))
        fields={'segments':changed,'audio_segments':self.state.audio} if track=='video' else {'audio_segments':changed}
        return self.commit('Mute '+track,replace(self.state,**fields))

    def delete_track_range(self,start,end,track):
        if track not in ('video','audio') or not 0<=start<end<=self.state.length: return False
        segs=self.state.segments if track=='video' else self.state.audio
        changed=compact(slice_segments(segs,0,start)+(Segment(None,0,end-start),)+slice_segments(segs,end,self.state.length))
        fields={'segments':changed,'audio_segments':self.state.audio} if track=='video' else {'audio_segments':changed}
        return self.commit('Supprimer '+track,replace(self.state,drawings=remove_key_range(self.state.drawings,start,end) if track=='video' and self.state.drawings_linked else self.state.drawings,**fields,position=min(start,self.state.length-1),selection=None,loop_range=None))

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
        return self.commit('Déplacer les clés de dessin',replace(self.state,drawings=keys,position=at,selection=(at,at+end-start)))

    def resize_drawing(self,start,new_start,new_end):
        keys=resize_key(self.state.drawings,start,new_start,new_end,self.state.length)
        return self.commit('Redimensionner la plage de dessin',replace(self.state,drawings=keys,selection=None))

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

    def exposure(self, value):
        return self.commit('Régler l’exposition',replace(self.state,exposure=round(float(value),2)))

    def to_data(self, all_media=False):
        return {'format':'cadence-studio','version':self.format_version(),'fps':str(self.fps),'media':[m for k,m in self.media.items() if all_media or any(s.media==k for s in self.state.segments+self.state.audio)],'state':asdict(self.state),'comparison':self.review,'drawing_transfer_id':self.drawing_transfer_id}

    def format_version(self):
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
        if data.get('format') != 'cadence-studio' or data.get('version') not in range(1,16):
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
        for seg in segs+(audio or ()):
            if seg.media is None:
                if not 0<=seg.start<seg.end: raise ValueError('Vide invalide.')
                continue
            if seg.media not in doc.media or not 0 <= seg.start < seg.end <= doc.media[seg.media]['frames']:
                raise ValueError('Plage de média invalide dans le projet.')
        length = sum(s.length for s in segs)
        sel = st.get('selection')
        if sel and not 0 <= sel[0] < sel[1] <= length: sel = None
        loop = st.get('loop_range')
        if loop and not 0 <= loop[0] < loop[1] <= length: loop = None
        ev = float(st.get('exposure',0))
        if not -10 <= ev <= 10: raise ValueError('Exposition invalide.')
        markers=st.get('frame_markers',[])
        if not isinstance(markers,(list,tuple)) or any(type(f) is not int or not 0<=f<length for f in markers): raise ValueError('Marqueurs invalides.')
        doc.state = State(segs,ev,max(0,min(int(st.get('position',0)),length)),tuple(sel) if sel else None,tuple(loop) if loop else None,bool(st.get("flip_h",False)),bool(st.get("flip_v",False)),audio,load_keys(st.get('drawings',[])),bool(st.get('drawings_linked',True)),tuple(sorted(set(markers))))
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
