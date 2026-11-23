# SPDX-License-Identifier: GPL-3.0-only
import json

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListWidget

from ui_text import tr


class MediaSources(QListWidget):
    mime_type = 'application/x-cadence-media-sources'

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def keys(self, items):
        return [item.data(Qt.ItemDataRole.UserRole) for item in sorted(items, key=self.row)]

    def mimeTypes(self):
        return [self.mime_type]

    def mimeData(self, items):
        data = QMimeData()
        data.setData(self.mime_type, json.dumps(self.keys(items)).encode('utf-8'))
        return data

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction


class MediaSourceDrops(QObject):
    def __init__(self, window):
        super().__init__(window.timeline)
        self.window = window
        timeline = window.timeline
        self.line = QFrame(timeline)
        self.line.setStyleSheet('background: #72e6cf; border: 0;')
        self.line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.line.hide()
        timeline.setAcceptDrops(True)
        timeline.installEventFilter(self)

    def track_menu(self, menu):
        window = self.window
        keys = window.media_list.keys(window.media_list.selectedItems())
        submenu = menu.addMenu(tr('Ajouter à la piste'))
        submenu.setEnabled(bool(keys) and not window.job)
        for track in window.doc.state.tracks:
            action = submenu.addAction(tr(track.info.name))
            action.triggered.connect(lambda checked=False, identity=track.info.id:
                                     window.edit_track_structure(window.doc.add_sources_to_track, identity, keys))
        return submenu

    def target(self, position):
        timeline = self.window.timeline
        if not timeline.state:
            return None
        x, y = position.x(), position.y()
        if timeline.simple:
            row = timeline.simple_track_rect()
            if not row.top() <= y <= row.bottom():
                return None
            track, top, height = timeline.active_media, row.top(), row.height()
        else:
            row = next(((track, top, height) for track, top, height in timeline.media_rows()
                        if top - 3 <= y < top + height - 3), None)
            if row is None:
                return None
            track, top, height = row
        if x < timeline.track_left():
            frame = track.length
        else:
            frame = max(0, min(round(timeline.raw_frame(x)), timeline.state.length))
            start = 0
            for segment in track.segments:
                end = start + segment.length
                if start < frame < end and segment.media is not None:
                    frame = start if frame - start <= end - frame else end
                    break
                start = end
        return track.info.id, frame, top, height

    def eventFilter(self, timeline, event):
        kind = event.type()
        if kind == QEvent.Type.DragLeave:
            self.line.hide()
            return False
        if kind not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        source = self.window.media_list
        if event.source() is not source or not event.mimeData().hasFormat(source.mime_type):
            return False
        target = self.target(event.position())
        if not target or self.window.job:
            self.line.hide()
            if kind == QEvent.Type.DragEnter and not self.window.job:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return True
        identity, frame, top, height = target
        if kind == QEvent.Type.Drop:
            self.line.hide()
            keys = json.loads(bytes(event.mimeData().data(source.mime_type)))
            self.window.edit_track_structure(self.window.doc.add_sources_to_track, identity, keys, frame)
        else:
            x = min(timeline.track_right(), max(timeline.track_left(), round(timeline.x_for(frame))))
            self.line.setGeometry(x - 1, int(top), 3, max(1, int(height) - 3))
            self.line.raise_()
            self.line.show()
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True
