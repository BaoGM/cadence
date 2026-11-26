# SPDX-License-Identifier: GPL-3.0-only
from bisect import bisect_right
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
import math
import re
from pathlib import Path


METHODS = ('held', 'blend', 'motion', 'rife', 'nvidia')


def points(value):
    if not isinstance(value, (list, tuple)) or len(value) == 1 or len(value) > 2048:
        raise ValueError('Courbe temporelle invalide.')
    result = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise ValueError('Courbe temporelle invalide.')
        x, y, method = point
        if (type(x) is not int or type(y) not in (int,float) or not math.isfinite(y) or min(x, y) < 0 or
                max(x, y) > 2**31-1 or method not in METHODS or (result and x <= result[-1][0])):
            raise ValueError('Courbe temporelle invalide.')
        result.append((x, y, method))
    return tuple(result)


def mapping(curve, frame):
    i = bisect_right(curve, frame, key=lambda p: p[0]) - 1
    if i < 0 or i == len(curve)-1:
        if i >= 0 and frame == curve[i][0]:
            y=curve[i][1]
            return math.floor(y), y-math.floor(y), curve[i][2]
        return frame, 0., 'held'
    x, y, method = curve[i]
    end, target, _ = curve[i+1]
    value=y+(frame-x)*(target-y)/(end-x)
    if abs(value-round(value))<1e-9: value=round(value)
    return math.floor(value),value-math.floor(value),method


def normalized(curve):
    result = points(curve)
    return () if all(x == y for x, y, _ in result) else result


def target(doc):
    from model import clip_at
    track = doc.active_track
    frame = doc.state.position
    selected = [(a,b) for track_id,a,b in doc.state.selected_clips if track_id == track.info.id]
    if len(selected) == 1:
        frame = selected[0][0]
    elif frame == track.video_length and frame == doc.state.length:
        frame -= 1
    hit = clip_at(track.segments, frame)
    if hit:
        index, start, clip = hit
        if clip.length > 1 and clip.media and doc.media[clip.media].get('has_video', True):
            return track, index, start, clip
    return None


@lru_cache(maxsize=512)
def _render_name(curve, fps, source_id):
    recipe = json.dumps([5, fps, source_id, curve], separators=(',', ':')).encode()
    return 'warp-' + hashlib.sha256(recipe).hexdigest()[:32] + '.nut'


def render_path(info, curve):
    from media import cache_root
    return _path(str(cache_root(create=False)),info['audio'],info['path'],str(info['fps']),curve)


@lru_cache(maxsize=512)
def _path(root, audio, source, fps, curve):
    key = Path(audio).parent.name
    if not re.fullmatch(r'[a-f0-9]{24}', key):
        key = hashlib.sha256(str(source).encode()).hexdigest()[:24]
    return Path(root) / key / _render_name(curve, fps, key)


def video_sample(info, clip, index):
    curve = clip.warp
    if not curve or not curve[0][0] <= index <= curve[-1][0]:
        return info, index
    return render_info(info, curve), index-curve[0][0]


def render_info(info, curve):
    path = str(render_path(info, curve))
    return dict(id=info['id'], path=path, proxy=path, width=info['width'], height=info['height'],
                fps=info['fps'], frames=curve[-1][0]-curve[0][0]+1,has_alpha=info.get('has_alpha',False),
                proxy_width=info.get('proxy_width',info['width']), proxy_height=info.get('proxy_height',info['height']))


def prepare_document(doc, progress, cancel):
    from time_warp_render import ensure_render
    variants = {(clip.media, clip.warp) for track in doc.state.tracks for clip in track.segments if clip.warp}
    for i,(key,curve) in enumerate(variants):
        ensure_render(doc.media[key], curve, lambda p,m:progress((i+p)/len(variants),m), cancel)


def export_tracks(state, media, sources, progress, cancel):
    from model import with_tracks
    from time_warp_render import ensure_render
    output = dict(media)
    tracks = []
    for track in state.tracks:
        segments = []
        for clip in track.segments:
            if not clip.warp or clip.muted or clip.media not in sources:
                segments.append(clip)
                continue
            curve = clip.warp
            low, high = curve[0][0], curve[-1][0]+1
            cuts = sorted({clip.start, clip.end, *(v for v in (low,high) if clip.start < v < clip.end)})
            pieces = []
            for a,b in zip(cuts,cuts[1:]):
                part = replace(clip, start=a, end=b, warp=())
                if low <= a < high:
                    info = media[clip.media]
                    key = ('time-warp', clip.media, curve)
                    if key not in output:
                        path = ensure_render(info,curve,progress,cancel)
                        output[key] = dict(render_info(info,curve), path=str(path))
                    part = replace(part, media=key, start=a-low, end=b-low)
                pieces.append(part)
            segments.extend(reversed(pieces) if clip.reversed else pieces)
        tracks.append(replace(track, segments=tuple(segments), audio_segments=track.audio))
    sources = list(dict.fromkeys(s.media for t in tracks for s in t.segments
                                 if s.media in output and not s.muted and output[s.media].get('has_video',True)))
    return with_tracks(state,tracks), output, sources
