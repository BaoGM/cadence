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

    def insert_library(self,payload,identity,frame):
        from media import prepare_batch
        from playlist_store import folder_tree_files
        window=self.window; panel=window.playlists_panel; doc=window.doc
        paths=payload.get('paths',[]); folder=None; records={}
        if 'node' in payload:
            entry,node=payload['node']
            if entry=='temporary':
                saved=next((item['doc'] for item in panel.temporary if item['id']==node),None)
                paths=panel.temporary_paths(saved) if saved else []
            elif node:
                folder=node; records=panel.store.entry(entry)['folders']
            else:
                paths=panel.store.files(entry)
        if not paths and not folder: return
        window.commit_exposure(); window.clip_tools.commit()
        tracks=doc.state.tracks; original_rate=doc.fps
        adopt_rate=not (doc.media or doc.project_path or doc.state.length or doc.undo_stack)
        rate=None if adopt_rate else doc.fps
        quality=window.preferences.get('preview_quality','native')
        def prepare(progress,cancel):
            sources=folder_tree_files(folder,records,cancel) if folder else paths
            return prepare_batch(sources,rate,progress,cancel,quality=quality,defer_audio=True)
        def success(items):
            if window.doc is not doc or doc.state.tracks!=tracks or doc.fps!=original_rate: return
            if doc.insert_track_sources(identity,items,frame,adopt_rate=adopt_rate):
                window.install_doc(doc)
        window.begin_media_open(paths or [folder], 'Ajout de médias',prepare,success)

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
            cursor = max(0,min(timeline.raw_frame(x),timeline.state.length))
            frame=round(cursor)
            start = 0
            for segment in track.segments:
                end = start + segment.length
                if start < cursor < end:
                    if segment.media is not None:
                        frame = start if cursor-start <= end-cursor else end
                    else:
                        audio_start=0
                        for sound in track.audio:
                            audio_end=audio_start+sound.length
                            if audio_start<cursor<audio_end and sound.media is not None:
                                left,right=max(start,audio_start),min(end,audio_end)
                                frame=left if cursor-left<=right-cursor else right
                                break
                            audio_start=audio_end
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
        from playlist_ui import LIBRARY_MIME
        source = self.window.media_list
        panel=getattr(self.window,'playlists_panel',None)
        library=panel and event.source() in (panel.tree,panel.files) and event.mimeData().hasFormat(LIBRARY_MIME)
        if not library and (event.source() is not source or not event.mimeData().hasFormat(source.mime_type)):
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
            if library:
                self.insert_library(json.loads(bytes(event.mimeData().data(LIBRARY_MIME))),identity,frame)
            else:
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
