# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import dataclass, replace

from model import MediaTrack, Segment, with_tracks


@dataclass(frozen=True)
class ClipEdge:
    segments: tuple
    index: int
    left: bool
    minimum: int
    maximum: int

    @classmethod
    def locate(cls, segments, index, left, frames):
        clip = segments[index]
        if left:
            before = frames-clip.end if clip.reversed else clip.start
            limits = -before, clip.length - 1
        else:
            tail = clip.start if clip.reversed else frames-clip.end
            limits = 1 - clip.length, tail
        return cls(segments, index, left, *limits)

    def moved(self, delta, preview=False):
        segments = self.segments
        clip = segments[self.index]
        before = segments[:self.index]
        if self.left:
            resized = clip.sliced(delta, clip.length)
            if preview and delta > 0:
                before += (Segment(None, 0, delta),)
            elif preview and delta < 0:
                # A restored head can temporarily cover neighbours until the ripple is committed.
                overlap = -delta
                index = len(before)
                while index and overlap >= before[index-1].length:
                    index -= 1
                    overlap -= before[index].length
                before = before[:index]
                if before and overlap:
                    last = before[-1]
                    before = before[:-1] + (last.sliced(0, last.length - overlap),)
        else:
            resized = clip.sliced(0, clip.length + delta)
        return before + (resized,) + segments[self.index + 1:]


@dataclass(frozen=True)
class ClipTrim:
    track: MediaTrack
    lane: str
    boundary: int
    edge: ClipEdge
    partner: ClipEdge | None

    @classmethod
    def find(cls, track, media, lane, index, left, linked):
        if lane not in ('video', 'audio'):
            return None
        segments, other = (track.segments, track.audio) if lane == 'video' else (track.audio, track.segments)
        if not 0 <= index < len(segments):
            return None
        clip = segments[index]
        frames = media.get(clip.media, {}).get('frames', 0)
        if not clip.media or not 0 <= clip.start < clip.end <= frames:
            return None
        end = sum(segment.length for segment in segments[:index + 1])
        boundary = end - clip.length if left else end
        edge = ClipEdge.locate(segments, index, left, frames)
        partner = None
        if linked and other is segments:
            partner = edge
        elif linked:
            at = 0
            for i, candidate in enumerate(other):
                end = at + candidate.length
                same_edge = (at == boundary and clip.source_frame(0) == candidate.source_frame(0) if left else
                             end == boundary and clip.source_frame(clip.length-1) == candidate.source_frame(candidate.length-1))
                if same_edge and candidate.media == clip.media and candidate.reversed == clip.reversed:
                    partner = ClipEdge.locate(other, i, left, frames)
                    break
                if at > boundary:
                    break
                at = end
        return cls(track, lane, boundary, edge, partner)

    def clamp(self, delta):
        lower, upper = self.edge.minimum, self.edge.maximum
        if self.partner:
            lower = max(lower, self.partner.minimum)
            upper = min(upper, self.partner.maximum)
        return max(lower, min(upper, delta))

    def apply(self, delta, *, preview=False):
        primary = self.edge.moved(delta, preview)
        if self.partner is self.edge:
            return replace(self.track, segments=primary, audio_segments=None)
        other = self.track.audio if self.lane == 'video' else self.track.segments
        secondary = self.partner.moved(delta, preview) if self.partner else other
        video, audio = (primary, secondary) if self.lane == 'video' else (secondary, primary)
        return replace(self.track, segments=video, audio_segments=None if video == audio else audio)


def trim_media(document, track_id, lane, index, left, delta, linked, *, follow_edge=False):
    tracks = list(document.state.tracks)
    for i, track in enumerate(tracks):
        if track.info.id == track_id:
            trim = ClipTrim.find(track, document.media, lane, index, left, linked)
            amount = trim.clamp(delta) if trim else 0
            if not amount:
                return False
            tracks[i] = trim.apply(amount)
            state = with_tracks(document.state, tracks)
            if state.selected_clips and (lane == 'video' or trim.partner):
                video_edge = trim.edge if lane == 'video' else trim.partner
                length = video_edge.segments[video_edge.index].length
                start = trim.boundary if left else trim.boundary - length
                end = start + length
                old = (track_id, start, end)
                shift = -amount if left else amount
                new = (track_id, start, end + shift)
                mapped = []
                for span in state.selected_clips:
                    owner, a, b = span
                    if span == old:
                        span = new
                    elif owner == track_id and a >= end:
                        span = (owner, a + shift, b + shift)
                    mapped.append(span)
                mapped.sort(key=lambda span: span[1])
                state = replace(state, selected_clips=tuple(mapped), selection=mapped[0][1:])
            if follow_edge:
                state = replace(state, position=trim.boundary if left else trim.boundary + amount - 1)
            elif state.position >= state.length:
                state = replace(state, position=max(0, state.length - 1))
            return document.commit('Redimensionner le clip', state, preserve_clip_selection=True)
    return False
