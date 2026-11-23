# SPDX-License-Identifier: GPL-3.0-only
import math
from bisect import bisect_left, bisect_right
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

from studio_icons import paint_icon
from timeline_index import SegmentIndex
from ui_text import language, tr


BASE = '#161d25'
HEAD = '#1b232c'
RULER = '#141b22'
BORDER = '#2a3440'
MINT = '#68e0cf'
AMBER = '#eab47e'
MUTED = '#9aaabb'
TEXT = '#e3eaf1'
ALIGN = Qt.AlignLeft | Qt.AlignVCenter


@lru_cache(maxsize=8)
def font(size, mono=False, bold=False):
    result = QFont('Consolas' if mono else 'Segoe UI')
    result.setPixelSize(size)
    if bold:
        result.setWeight(QFont.Weight.DemiBold)
    return result


def label(p, area, text, color=TEXT, size=12, mono=False, bold=False, align=ALIGN):
    if area.width() < 5:
        return
    p.setFont(font(size, mono, bold))
    shown = p.fontMetrics().elidedText(text, Qt.ElideRight, int(area.width()))
    p.setPen(QColor(color))
    p.drawText(area, align, shown)


def line(p, x1, y1, x2, y2, color, width=1):
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.FlatCap))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def flag(p, x, y, height=11, color=AMBER):
    paint_icon(p, QRectF(x-3, y-1, height+3, height+3), 'mark', color)


def headers(t, p):
    width = t.track_left()
    p.fillRect(QRectF(0, 0, width, t.height()), QColor(HEAD))
    ruler_y = t.ruler_y()
    p.fillRect(QRectF(0, ruler_y, width, 26), QColor(RULER))
    if not t.state or not t.state.selection:
        label(p, QRectF(10, ruler_y, width - 16, 25), tr('Temps'), MUTED, 11, True)
    if not t.simple:
        for y, title in ((0, 'Marqueurs'), (22, 'Clés de dessin')):
            if y == 0:
                flag(p, 10, 5)
            else:
                paint_icon(p, QRectF(8,y+3,15,15), 'exposure', MUTED)
            label(p, QRectF(29, y, width - 55, 22), tr(title), MUTED, 11)
            tone = MUTED if t.can_add_at_cursor(y==0) else '#556472'
            paint_icon(p, QRectF(width-23,y+3,15,15), 'plus', tone)
            line(p, 0, y + 21.5, t.width(), y + 21.5, BORDER)
    rows = [(t.active_media, 27, 25)] if t.simple else t.media_rows()
    for track, y, height in rows:
        if t.simple and getattr(t, 'cross_origin', None) and t.gesture in ('move', 'copy', 'transfer'):
            track = next((other for other in t.state.tracks if other.info.id != t.cross_origin[0]), track)
        chosen = track.info.id in getattr(t, 'selected_media_ids', (t.active_media.info.id,))
        top = 26 if t.simple else y - 3
        h = 26 if t.simple else t.video_height(track)
        if chosen or getattr(t, 'cross_target', None) == track.info.id:
            p.fillRect(QRectF(0, top, width, h), QColor('#223438'))
            p.fillRect(QRectF(0, top, 2, h), QColor(MINT))
        cy = top + h / 2
        if t.simple:
            paint_icon(p, QRectF(9,cy-7,14,14), 'film', MUTED)
            if t.state and len(t.state.tracks) > 1:
                paint_icon(p, QRectF(width-25,cy-7,14,14), 'down', MUTED)
        else:
            paint_icon(p, QRectF(6,cy-7,14,14), 'down' if track.info.audio_expanded else 'right', MINT if chosen else MUTED)
            paint_icon(p, QRectF(width-25,cy-8,16,16), 'sound' if track.info.audio_enabled else 'mute', MUTED if track.info.audio_enabled else AMBER)
        label(p, QRectF(28, top, width - 57, h), tr(track.info.name), MINT if chosen else '#bfccd9', 12, bold=True)
        if not t.simple and track.info.audio_expanded:
            audio_y = top + h
            paint_icon(p, QRectF(12,audio_y+4,13,13), 'wave', '#9cb5b2')
            label(p, QRectF(31, audio_y, width - 36, 22), tr('Audio'), MUTED, 11)
            line(p, 0, audio_y - .5, t.width(), audio_y - .5, BORDER)
        line(p, 0, top + (26 if t.simple else height) - .5, t.width(), top + (26 if t.simple else height) - .5, BORDER)
    line(p, width - .5, 0, width - .5, t.height(), '#333f4c')


def ruler(t, p):
    left, top = t.track_left(), t.ruler_y()
    p.fillRect(QRectF(left, top, t.width() - left, 26), QColor(RULER))
    line(p, 0, top + 25.5, t.width(), top + 25.5, BORDER)
    if not t.state or not t.state.length:
        return
    minor, major = t.ruler_steps()
    # In seconds mode use whole seconds for spacious graduations, including fractional rates.
    if t.units != 'frames' and t.span() / t.fps >= 4:
        ticks = max(4, min(16, t.track_width() / 48))
        sec = max(1, math.ceil(t.span() / (ticks * t.fps)))
        major = sec * t.fps
        minor = major / 4
    end = min(t.state.length, t.view_start + t.span())
    p.setFont(font(10, True))
    metrics = p.fontMetrics()
    for index in range(max(0, math.ceil(t.view_start / minor)), math.floor(end / minor) + 1):
        frame = index * minor
        large = abs(frame / major - round(frame / major)) < .00001
        x = t.x_for(frame) + .5
        if large:
            line(p, x, top + 19, x, top + 25, '#788794')
            if x > left + 1:
                line(p, x, top + 26, x, t.height(), '#27313b')
                if top: line(p, x, 0, x, top, '#2b3540')
            text = str(round(frame)) if t.units == 'frames' else (f'{round(frame / t.fps):02d}s' if major >= t.fps else t.tick_label(round(frame)))
            label_width = metrics.horizontalAdvance(text) + 2
            label_x = min(x + 3, t.width() - label_width - 2)
            label(p, QRectF(label_x, top + 1, label_width, 16), text, '#9cabb9', 10, True)
        else:
            line(p, x, top + 22, x, top + 25, '#475561')


def cover(p, dest, image):
    if dest.width() <= 0 or dest.height() <= 0 or image.isNull():
        return
    scale = max(dest.width() / image.width(), dest.height() / image.height())
    w, h = dest.width() / scale, dest.height() / scale
    p.drawImage(dest, image, QRectF((image.width() - w) / 2, (image.height() - h) / 2, w, h))


def card(p, t, rect, segment, meta, selected, lower, expanded):
    if segment.media is None:
        return
    fill = '#31625e' if selected else ('#303b50' if lower else '#2d4249' if t.simple else '#2e454c')
    stroke = MINT if selected else '#4a566b' if lower else '#425a62' if t.simple else '#47616c'
    point=getattr(t,'hover_point',None)
    if point is not None and rect.contains(point) and not selected:
        stroke='#91bab7' if not lower else '#a0b4d3'
    if segment.muted:
        fill, stroke = '#303941', '#56606a'
    p.setPen(QPen(QColor(stroke), 1.5 if selected else 1))
    p.setBrush(QColor(fill))
    p.drawRoundedRect(rect, 3, 3)
    if rect.width() < 8 or t.simple and not segment.muted:
        return
    p.save()
    p.setClipRect(rect.adjusted(1, 1, -1, -1), Qt.IntersectClip)
    if segment.muted:
        x = rect.left() - rect.height()
        while x < rect.right():
            line(p, x, rect.bottom(), x + rect.height(), rect.top(), '#39454d')
            x += 9
    text_y = rect.top()
    if t.simple:
        p.restore()
        return
    text_h = rect.height()
    thumb_left = rect.left() + 5
    text_x = thumb_left
    if not t.simple and rect.width() >= 68:
        images = t.thumbnails.get(meta, segment, expanded)
        if expanded:
            text_h = min(27, rect.height() / 2 + 1)
            if len(images)>1:
                y = rect.top() + text_h + 1
                width = (rect.width() - 4) / 7
                for index in range(7):
                    target = QRectF(rect.left() + 2 + index * width, y, width - 1, rect.bottom() - y - 2)
                    cover(p, target, images[min(index, len(images)-1)])
        h = min(27, text_h - 4)
        thumb = QRectF(thumb_left, rect.top() + (text_h - h) / 2, min(47, rect.width() * .3), h)
        if images:
            cover(p, thumb, images[0])
        else:
            p.fillRect(thumb, QColor('#23323c'))
            paint_icon(p, QRectF(thumb.center().x()-8,thumb.center().y()-8,16,16), 'wave' if meta.get('has_video') is False else 'film', '#84949f')
        text_x = thumb.right() + 6
    right = rect.right() - 5
    if not t.simple and right - text_x > 90:
        seconds = f'{segment.length / t.fps:.1f}'.rstrip('0').rstrip('.')
        if language() == 'fr':
            seconds = seconds.replace('.', ',')
        duration = seconds + ' s'
        p.setFont(font(10, True))
        width = p.fontMetrics().horizontalAdvance(duration) + 2
        label(p, QRectF(right - width, text_y, width, text_h), duration, '#b4c2c8', 10, True, align=Qt.AlignRight | Qt.AlignVCenter)
        right -= width + 6
    label(p, QRectF(text_x, text_y, right - text_x, text_h), meta.get('name', '') + (tr(' · DÉSACTIVÉ') if segment.muted else ''), '#d7eaeb', 11 if t.simple else 12)
    p.restore()


def waveform(p, t, segment, media, y, x1, x2, enabled):
    if segment.media is None:
        return
    left, right = max(t.track_left(), x1), min(t.track_right(), x2)
    wave = t.wave.get(segment.media)
    mid = y + 11
    tint = '#61716f' if segment.muted or not enabled else '#68aa9e'
    line(p, left, mid, right, mid, tint)
    if wave is None or not len(wave):
        return
    frames = max(1, media.get('frames', segment.end))
    path = QPainterPath()
    for x in range(math.ceil(left), math.ceil(right), 2):
        frame = segment.start + (x - x1) / max(1, x2 - x1) * segment.length
        idx = max(0, min(len(wave) - 1, int(frame / frames * len(wave))))
        amp = min(9, float(wave[idx]) * 9)
        path.moveTo(x, mid - amp)
        path.lineTo(x, mid + amp)
    p.setPen(QPen(QColor(tint), 1.3, Qt.SolidLine, Qt.FlatCap))
    p.drawPath(path)


def tracks(t, p):
    rows = [(t.active_media, 27, 26)] if t.simple else t.media_rows()
    for track, y, height in rows:
        lower = track.info.id != t.state.tracks[0].info.id
        h = 21 if t.simple else t.video_height(track) - 6
        selected_tracks = getattr(t, 'selected_media_ids', (t.active_media.info.id,))
        ranges = t.state.selection_ranges(track.info.id) if track.info.id in selected_tracks and t.selection_track != 'drawing' else ()
        kinds = [('video', track.segments)]
        if track.info.audio_expanded and not t.simple:
            kinds.append(('audio', track.audio))
        for kind, segments in kinds:
            idx = (track.info.id, kind)
            if idx not in t.track_indices:
                t.track_indices[idx] = SegmentIndex()
            last_pixel = None
            for _, at, seg in t.track_indices[idx].visible(segments, t.view_start, t.view_start + t.span()):
                x1, x2 = t.x_for(at), t.x_for(at + seg.length)
                if x2 <= t.track_left() or x1 >= t.track_right() or (x2 - x1 < 1 and math.floor(x1) == last_pixel):
                    continue
                last_pixel = math.floor(x1)
                meta = t.media.get(seg.media, {})
                if kind == 'audio':
                    waveform(p, t, seg, meta, y + t.video_height(track) - 3, x1, x2, track.info.audio_enabled)
                    continue
                left = max(t.track_left() + 1.5, x1 + 2)
                right = min(t.track_right() - .5, x2 - 2)
                rect = QRectF(left, y + .5, max(1, right - left), h)
                chosen = any(a <= at and b >= at + seg.length for a, b in ranges)
                card(p, t, rect, seg, meta, chosen, lower, track.info.audio_expanded)
        for a, b in ranges:
            left = max(t.track_left(), t.x_for(a))
            right = min(t.track_right(), t.x_for(b))
            if right <= left:
                continue
            p.fillRect(QRectF(left, y, right - left, h + 1), QColor(104, 224, 207, 62))
            line(p, left, y+1, right, y+1, MINT, 2)
            line(p, left, y+h-1, right, y+h-1, MINT, 2)
            line(p, left + 1, y, left + 1, y + h, MINT, 2)
            line(p, right - 1, y, right - 1, y + h, MINT, 2)


def marker_areas(t, region=None):
    if not t.state or not t.state.frame_markers:
        return
    points = t.state.frame_markers
    y, h = (27, 21) if t.simple else (0, 21)
    if region is not None and not y <= region.y() <= y+h:
        return
    left, right = t.track_left(), t.track_right()
    start, end = t.view_start, t.view_start + t.span()
    if region is not None:
        start = max(start, t.raw_frame(region.x()-145))
        end = min(end, t.raw_frame(region.x()+145))
    first, last = bisect_left(points,start), bisect_right(points,end)
    last_x = left-8
    for i in range(first,last):
        x = min(t.x_for(points[i])+1, right-10)
        if x-last_x < 4: continue
        last_x = x
        next_x = min(right, t.x_for(points[i+1])) if i+1<len(points) else right
        space = next_x-x-13
        if next_x==right and space<74:
            previous = max(left,t.x_for(points[i-1])+12) if i else left
            text_area=QRectF(max(previous,x-127),y,max(0,min(125,x-previous-2)),h)
        else:
            text_area=QRectF(x+12,y,min(125,max(0,space)),h)
        yield i, points[i], QRectF(x,y,11,h), text_area


def marker_label(t, i, frame):
    names = t.state.marker_names
    if names is not getattr(t, '_marker_name_source', None):
        t._marker_name_source, t._marker_name_map = names, dict(names)
    return t._marker_name_map.get(frame,'')


def marker_at(t, point):
    from PySide6.QtGui import QFontMetrics
    metrics = QFontMetrics(font(11))
    for index, frame, flag_area, text_area in marker_areas(t,point):
        if flag_area.contains(point) or text_area.contains(point):
            text = marker_label(t,index,frame)
            ink_width=metrics.horizontalAdvance(text)
            on_text = point.x() >= text_area.right()-ink_width if text_area.right()<flag_area.left() else point.x() <= text_area.left()+ink_width
            if flag_area.contains(point) or text and on_text:
                return frame, text
    return None


def markers(t, p):
    drag=t.marker_drag
    for i, frame, area, text_area in marker_areas(t):
        if drag.destination is not None and drag.source==frame:
            continue
        hover = getattr(t,'hover_marker',None)==frame
        selected = t.state.position==frame
        x = area.left()
        if hover or selected:
            p.setPen(QPen(QColor('#a78156' if selected else '#685341'), 1))
            p.setBrush(QColor('#514031' if hover else '#41372e'))
            p.drawRoundedRect(area.adjusted(0,.5,0,-.5), 2, 2)
        flag(p, x, area.center().y()-6, 12, '#ffcf96' if hover or selected else AMBER)
        align = Qt.AlignRight | Qt.AlignVCenter if text_area.right()<x else ALIGN
        label(p, text_area, marker_label(t,i,frame), '#ffe0b9' if hover or selected else '#d8b795', 11, align=align)
    if drag.destination is not None:
        x=min(t.x_for(drag.destination)+1,t.track_right()-10)
        y=27 if t.simple else 0
        color='#ffe0b9' if drag.valid() else '#ff8b81'
        line(p,x,y,x,y+21,color)
        flag(p,x,y+4,12,color)
        if drag.name:
            label(p,QRectF(x+13,y,min(125,t.track_right()-x-14),21),drag.name,color,11)


def paint(t, p):
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.fillRect(t.rect(), QColor(BASE))
    headers(t, p)
    ruler(t, p)
    if not t.state or not t.state.length:
        y = 26 if t.simple else 70
        label(p, QRectF(t.track_left() + 8, y, t.track_width() - 16, t.height() - y), tr('Votre montage apparaîtra ici.'), MUTED, 11)
        return
    p.save()
    p.setClipRect(QRectF(t.track_left(), 0, t.track_width(), t.height()))
    tracks(t, p)
    t.paint_current_highlight(p)
    t.paint_hover_highlight(p)
    if t.simple:
        t.drawing_track.paint_simple(p)
    else:
        t.drawing_track.paint(p)
    markers(t, p)
    if t.state.loop_range:
        a, b = t.state.loop_range
        line(p, t.x_for(a), t.height()-2, t.x_for(b), t.height()-2, AMBER, 2)
    x = t.x_for(t.state.position) + .5
    if t.track_left() <= x <= t.track_right():
        line(p, x, 0, x, t.height(), MINT, 1.5)
        y = t.ruler_y()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(MINT))
        p.drawPolygon(QPolygonF([QPointF(x-5, y), QPointF(x+5, y), QPointF(x+5, y+5), QPointF(x, y+10), QPointF(x-5, y+5)]))
    if t.frame_indicator() is not None:
        t.paint_frame_indicator(p)
    p.restore()
    t.paint_selection_label(p)
    t.clip_preview.paint(p)
