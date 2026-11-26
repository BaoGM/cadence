# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor
from typing import NamedTuple

from clip_trim import ClipTrim
from model import MediaTrack, Segment
from timeline_index import SegmentIndex


class TrimFrame(NamedTuple):
    track: MediaTrack
    segment: Segment
    position: int
    source: int


class TimelineTrim:
    grip = 14

    def __init__(self, timeline):
        self.timeline = timeline
        self.plan = None
        self.preview_track = None
        self.frame = None
        self.delta = 0

    def hit(self, point):
        t = self.timeline
        x, y = point.x(), point.y()
        if not t.state or not t.track_left() <= x <= t.track_right() + self.grip:
            return
        if t.simple:
            row = t.simple_track_rect()
            if not row.top() <= y <= row.bottom():
                return
            track, lane = t.active_media, 'video'
            top, height = row.top(), row.height()
        else:
            for track, top, height in t.media_rows():
                if top - 3 <= y < top + height - 3:
                    break
            else:
                return
            video_height = t.video_height(track)
            if track.info.audio_expanded and y >= top + video_height - 3:
                lane, top, height = 'audio', top + video_height - 3, 20
            else:
                lane, height = 'video', video_height - 6
        segments = track.segments if lane == 'video' else track.audio
        key = track.info.id, lane
        if key not in t.track_indices:
            t.track_indices[key] = SegmentIndex()
        best = None
        for index, at, segment in t.track_indices[key].visible(segments, t.raw_frame(x - self.grip), t.raw_frame(x + self.grip)):
            if segment.media is None:
                continue
            begin, end = t.x_for(at), t.x_for(at + segment.length)
            inside = begin <= x < end
            tolerance = min(self.grip, (end - begin) / 3) if inside else self.grip
            if inside and min(x - begin, end - x) > tolerance:
                return None
            for left, boundary in ((True, begin), (False, end)):
                distance = abs(x - boundary)
                if distance > tolerance or boundary < t.track_left() - .01 or boundary > t.track_right() + .01:
                    continue
                priority = (not inside, distance)
                if best is None or priority < best[0]:
                    best = priority, (track, lane, index, left, top, height, boundary)
        return best[1] if best is not None else None

    def show_frame(self, track, segment, boundary, left, force=False):
        frame = TrimFrame(track, segment, max(0, boundary if left else boundary - 1),
                          segment.source_frame(0 if left else segment.length - 1))
        if force or self.frame != frame or self.timeline.state.position != frame.position:
            self.frame = frame
            self.timeline.trimPreviewChanged.emit(frame)

    def hover(self, hit):
        if hit:
            track, lane, index, left, _, _, x = hit
            segment = (track.segments if lane == 'video' else track.audio)[index]
            self.show_frame(track, segment, round(self.timeline.raw_frame(x)), left)
        elif self.frame is not None:
            self.clear_preview()

    def clear_preview(self, redraw=True):
        self.preview_track = None
        had_frame = self.frame is not None
        self.frame = None
        if had_frame and redraw:
            self.timeline.trimPreviewChanged.emit(None)

    def visible_length(self, length):
        return max(length, self.preview_track.length) if self.preview_track is not None else length

    def start(self, event):
        if event.modifiers() != Qt.NoModifier:
            return False
        hit = self.hit(event.position())
        if hit is None:
            self.hover(None)
            return False
        t = self.timeline
        track, lane, index, left, self.top, self.height, _ = hit
        self.plan = ClipTrim.find(track, t.media, lane, index, left, t.linked)
        if self.plan is None:
            return False
        self.delta = 0
        self.dragged = False
        self.linked = t.linked
        self.original_view = t.view_start
        t.gesture = 'trim'
        t.selection_track = lane
        t.setCursor(Qt.SizeHorCursor)
        self.show_frame(track, self.plan.edge.segments[index], self.plan.boundary, left, force=True)
        event.accept()
        return True

    def move(self, event):
        t = self.timeline
        dx = t._timeline_drag.move(event.globalPosition()).x()
        self.dragged |= abs(dx) >= 3
        if self.dragged:
            delta = self.plan.clamp(round(dx * t.drag_scale))
            if delta != self.delta:
                self.delta = delta
                self.preview_track = self.plan.apply(delta, preview=True) if delta else None
                edge = self.plan.edge
                clip = edge.segments[edge.index]
                resized = clip.sliced(delta, clip.length) if edge.left else clip.sliced(0, clip.length + delta)
                self.show_frame(self.plan.track, resized, self.plan.boundary + delta, edge.left)
            t.ensure_visible(self.frame.position)
        t.setCursor(Qt.SizeHorCursor)
        t.update()

    def release(self, event):
        t = self.timeline
        self.move(event)
        plan, delta = self.plan, self.delta
        frame = self.frame.position
        t._timeline_drag.finish()
        t.clear_clip_drag(restore_preview=False)
        if delta:
            t.mediaTrimmed.emit(plan.track.info.id, plan.lane, plan.edge.index, plan.edge.left, delta, self.linked)
        else:
            t.mediaEdgeFocused.emit(frame)

    def displayed_track(self, track):
        if self.preview_track is not None and self.plan and track.info.id == self.plan.track.info.id:
            return self.preview_track
        return track

    def selection_ranges(self, track, ranges):
        plan = self.plan
        if (not ranges or not plan or not plan.edge.left or self.delta <= 0
                or track.info.id != plan.track.info.id or (plan.lane == 'audio' and not plan.partner)):
            return ranges
        start, end = plan.boundary, plan.boundary + self.delta
        return tuple((a,b) for left,right in ranges
                     for a,b in ((left,min(right,start)),(max(left,end),right)) if b>a)

    def paint(self, painter):
        t = self.timeline
        if self.plan is None:
            point = getattr(t, 'hover_point', None)
            if point is not None and t.anchor is None and t.cursor().shape() == Qt.SizeHorCursor and t.hover_marker is None:
                hit = self.hit(point)
                if hit:
                    _, _, _, left, top, height, x = hit
                    y = top + 2
                    ink = QColor('#9ceae0')
                    painter.fillRect(QRectF(x if left else x - 2, y, 2, height - 4), ink)
                    for cap in (y, y + height - 6):
                        painter.fillRect(QRectF(x if left else x - 5, cap, 5, 2), ink)
            return
        if not self.dragged:
            return
        boundary = max(0, self.plan.boundary + self.delta)
        new = t.x_for(boundary)
        painter.save()
        painter.setClipRect(QRectF(t.track_left(), self.top, t.track_width(), self.height))
        painter.fillRect(QRectF(new - 1, self.top, 2, self.height), QColor('#67ddcd'))
        painter.restore()
