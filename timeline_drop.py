# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPen

from model import locate
from ui_text import tr


class ClipDragPreview:
    def __init__(self, timeline):
        self.timeline = timeline
        self.motion = QVariantAnimation(timeline)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(lambda value: timeline.update())
        self.motion.finished.connect(self.finish)
        self.phase = None
        self.description = ''

    def animate(self, phase, duration):
        self.motion.stop()
        self.phase = phase
        self.motion.setDuration(duration)
        self.motion.setStartValue(0.)
        self.motion.setEndValue(1.)
        self.motion.start()

    def finish(self):
        if self.phase == 'land':
            self.phase = None
            self.timeline.update()

    def clear(self):
        self.motion.stop()
        self.phase = None
        self.description = ''
        self.timeline.setAccessibleDescription('')
        self.timeline.update()

    def lift(self):
        t = self.timeline
        start, end, kind = t.move_span
        self.length = end - start
        self.copying = t.gesture == 'copy' or t.gesture == 'transfer' and t.cross_copy
        self.kind = 'video' if t.linked or self.copying else kind
        self.track_id = t.active_media.info.id
        segments = t.active_media.audio if kind == 'audio' else t.active_media.segments
        media_id = locate(segments, start)[0] if 0 <= start < t.active_media.length else None
        self.name = t.media.get(media_id, {}).get('name', '')
        self.animate('lift', 110)

    def describe_target(self):
        t = self.timeline
        if t.drop_frame is None:
            return
        label = tr('Copie : image' if self.copying else 'Insertion : image') + ' ' + str(t.drop_frame)
        routing = tr('vidéo + audio') if t.linked or self.copying or t.gesture=='transfer' else tr('Audio' if self.kind=='audio' else 'Vidéo')
        self.description = label + ' · ' + routing
        if t.leave_gap and not self.copying and t.gesture!='transfer':
            self.description += tr(' · vide conservé')
        t.setAccessibleDescription(self.description)

    def row(self, track_id):
        t = self.timeline
        if t.simple:
            return t.simple_track_rect().adjusted(0, 2, 0, 0)
        for track, y, height in t.media_rows():
            if track.info.id == track_id:
                audio = self.kind == 'audio' and track.info.audio_expanded
                offset = t.video_height(track) if audio else 0
                return QRectF(t.track_left(), y + offset, t.track_width(), 16 if audio else t.video_height(track) - 6)
        return QRectF()

    def card(self, x, track_id, lift):
        t = self.timeline
        row = self.row(track_id)
        if row.isEmpty():
            return QRectF()
        width = min(row.width(), max(5, t.x_for(self.length) - t.x_for(0) - 1))
        left = max(row.left(), min(x, row.right() - width))
        return QRectF(left, row.top() - lift, width, row.height())

    def current_rect(self):
        t = self.timeline
        progress = self.motion.currentValue() or 0.
        if self.phase == 'land':
            end = self.card(t.x_for(self.destination), self.track_id, 0)
            origin = self.release_rect
            return QRectF(origin.x() + (end.x() - origin.x()) * progress,
                          origin.y() + (end.y() - origin.y()) * progress,
                          origin.width() + (end.width() - origin.width()) * progress,
                          origin.height() + (end.height() - origin.height()) * progress)
        return self.card(t.ghost_x, getattr(t, 'cross_target', None) or self.track_id, progress * 4)

    def land(self, release_rect, destination, track_id):
        self.release_rect = release_rect
        self.destination = destination
        self.track_id = track_id
        self.animate('land', 155)

    def paint(self, painter):
        if self.phase is None:
            return
        t = self.timeline
        rect = self.current_rect()
        if rect.isEmpty():
            return
        painter.save()
        painter.setClipping(False)
        margin_top = t.simple_track_rect().top() - 5 if t.simple else 44
        painter.setClipRect(QRectF(t.track_left(), margin_top, t.track_width(), t.height()-margin_top))
        accent = QColor('#72e6cf' if self.copying else '#ffb665')
        if self.phase == 'lift':
            if not self.copying:
                origin = self.card(t.x_for(t.move_span[0]), self.track_id, 0)
                painter.fillRect(origin, QColor(6, 12, 17, 150))
            target = t.animated_x
            if target is not None and (t.gesture != 'transfer' or t.cross_target):
                row = self.row(getattr(t, 'cross_target', None) or self.track_id)
                painter.setPen(QPen(accent, 2))
                painter.drawLine(QPointF(target, row.top()-4), QPointF(target, row.bottom()+2))
                painter.drawLine(QPointF(target-3, row.top()-3), QPointF(target+3, row.top()-3))
        else:
            painter.setOpacity(max(0., 1. - (self.motion.currentValue() or 0.) ** 3))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 75))
        painter.drawRoundedRect(rect.translated(0, 2), 4, 4)
        painter.setPen(QPen(accent, 1.4))
        painter.setBrush(QColor('#214b49' if self.copying else '#68452a'))
        painter.drawRoundedRect(rect.adjusted(.8,.8,-.8,-.8), 4, 4)
        font = QFont('Segoe UI'); font.setPixelSize(11); painter.setFont(font)
        command = tr('Copie' if self.copying else 'Déplacer')
        info = self.description if self.phase=='lift' else command
        label = ' · '.join(part for part in (info, self.name, str(self.length) + ' ' + tr('img')) if part)
        inner = rect.adjusted(6, 0, -6, 0)
        if inner.width() > painter.fontMetrics().horizontalAdvance('…'):
            painter.setPen(QColor('#f1f4f6'))
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter,
                             painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(inner.width())))
        painter.restore()
