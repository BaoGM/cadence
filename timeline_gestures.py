# SPDX-License-Identifier: GPL-3.0-only
from bisect import bisect_left

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFrame
from shiboken6 import isValid

from drag import ContinuousDrag
from timeline_skin import marker_at


class BandScrub(QObject):
    def __init__(self, timeline, band):
        super().__init__(band)
        self.timeline = timeline
        self.band = band
        self.pressed = None
        for widget in (band, *band.findChildren(QFrame)):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    def eventFilter(self, widget, event):
        kind = event.type()
        if kind not in (QEvent.Leave,QEvent.Hide,QEvent.WindowDeactivate,QEvent.MouseButtonPress,QEvent.MouseMove,QEvent.MouseButtonRelease):
            return False
        t = getattr(self,'timeline',None)
        if t is None or not isValid(t):
            return False
        if kind == QEvent.Leave and self.pressed is None:
            t.hover_x = None
            t.update()
            return False
        if kind in (QEvent.Hide, QEvent.WindowDeactivate) and self.pressed is widget:
            self.pressed = None
            t.finish_range_drag()
            return False
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease) or not t.state or not t.state.length:
            return False
        x = t.mapFromGlobal(event.globalPosition()).x()
        frame = t.frame_for(x)
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if event.modifiers() & ~Qt.ShiftModifier:
                return False
            self.pressed = widget
            t.setFocus(Qt.MouseFocusReason)
            t.begin_range_drag(frame)
        elif self.pressed is not widget:
            if kind == QEvent.MouseMove:
                t.hover_x = x
                t.update()
            return False
        if kind == QEvent.MouseButtonRelease:
            if event.button() != Qt.LeftButton:
                return False
            if frame != t.range_frame:
                t.update_range_drag(frame, event.modifiers())
            self.pressed = None
            t.finish_range_drag()
        else:
            t.update_range_drag(frame, event.modifiers())
        t.hover_x = x
        t.update()
        event.accept()
        return True


class MarkerDrag(QObject):
    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self.source = None
        self.destination = None
        timeline.installEventFilter(self)

    def eventFilter(self, widget, event):
        t = self.timeline
        kind = event.type()
        if self.source is None:
            if kind != QEvent.MouseButtonPress or event.button() != Qt.LeftButton or event.modifiers() != Qt.NoModifier:
                return False
            hit = marker_at(t, event.position())
            if not hit:
                return False
            t.setFocus(Qt.MouseFocusReason)
            self.source, self.name = hit
            self.points = t.state.frame_markers
            self.drag = ContinuousDrag(event.globalPosition())
            self.scale = t.span() / t.track_width()
            self.moved = False
        elif kind == QEvent.MouseMove or kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            dx = self.drag.move(event.globalPosition()).x()
            if not t.state or self.points is not t.state.frame_markers:
                self.finish()
                return True
            if abs(dx) >= 3:
                self.moved = True
            if self.moved:
                self.destination = max(0, min(t.state.length-1, self.source + round(dx*self.scale)))
                t.ensure_visible(self.destination)
                t.setCursor(Qt.ClosedHandCursor if self.valid() else Qt.ForbiddenCursor)
            if kind == QEvent.MouseButtonRelease:
                source, target, moved, valid = self.source, self.destination, self.moved, self.valid()
                self.finish()
                if not moved:
                    t.seek.emit(source)
                elif valid and target != source:
                    t.markerMoved.emit(source, target)
        elif kind == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            event.accept()
            return True
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.finish()
        elif kind in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.FocusOut):
            self.finish()
            return False
        else:
            return False
        t.update()
        event.accept()
        return True

    def valid(self):
        if self.destination is None or self.destination == self.source:
            return True
        index = bisect_left(self.points, self.destination)
        return index == len(self.points) or self.points[index] != self.destination

    def finish(self):
        self.drag.finish()
        self.source = self.destination = self.points = None
        self.timeline.unsetCursor()
        self.timeline.update()
