# SPDX-License-Identifier: GPL-3.0-only
from datetime import datetime
from fractions import Fraction
from threading import Thread
from library_style import icon, style_button
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QFile, QSignalBlocker
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from shiboken6 import isValid
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
                              QListWidget, QListWidgetItem, QAbstractItemView, QPushButton,
                              QMenu, QFileDialog, QInputDialog, QMessageBox, QSplitter, QApplication,
                              QScrollArea, QLayout, QLabel)

from playlist_store import PlaylistStore, scan_folder, has_subfolders, copy_into_folder, path_key, VIDEO_EXTENSIONS
from ui_text import tr


class PlaylistFiles(QListWidget):
    filesDropped = Signal(list)
    playRequested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.play_press = None

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self.play_press = (item.data(Qt.ItemDataRole.UserRole), event.position().toPoint()) if item and event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.play_press and (event.position().toPoint()-self.play_press[1]).manhattanLength() >= QApplication.startDragDistance():
            self.play_press = None
        super().mouseMoveEvent(event)

    def startDrag(self, actions):
        self.play_press = None
        super().startDrag(actions)

    def mouseReleaseEvent(self, event):
        pressed = self.play_press; self.play_press = None
        item = self.itemAt(event.position().toPoint())
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        super().mouseReleaseEvent(event)
        if pressed and pressed[0] == path and event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if (event.position().toPoint()-pressed[1]).manhattanLength() < QApplication.startDragDistance():
                self.playRequested.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            self.filesDropped.emit(paths); event.acceptProposedAction()
        else: super().dropEvent(event)


class PlaylistPanel(QWidget):
    scanFinished = Signal(object, object, str)

    def __init__(self, window):
        super().__init__(window)
        self.w = window; self.temporary = []; self.serial = 0; self.current = None; self.rebuilding = False
        self.scans = {}; self.pending_open = None
        self.scanFinished.connect(self.folder_scanned)
        self.pending_playback = None
        self.play_timer = QTimer(self); self.play_timer.setInterval(20)
        self.play_timer.timeout.connect(self.start_file_playback)
        self.store = None
        try: self.store = PlaylistStore()
        except (OSError, ValueError) as error:
            QTimer.singleShot(0, lambda text=str(error): window.error(text))
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(); scroll.setWidget(content); outer.addWidget(scroll)
        layout = QVBoxLayout(content); layout.setContentsMargins(2, 2, 2, 2)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        row = QHBoxLayout()
        new = QPushButton(tr('Nouveau…')); new.clicked.connect(self.create_menu); row.addWidget(new)
        self.open_button = QPushButton(tr('Ouvrir')); self.open_button.clicked.connect(self.open_current); row.addWidget(self.open_button)
        self.refresh_button = QPushButton(tr('Actualiser')); self.refresh_button.clicked.connect(lambda: self.browse(refresh=True)); row.addWidget(self.refresh_button)
        layout.addLayout(row)
        style_button(new,'plus'); style_button(self.open_button,'open'); style_button(self.refresh_button,'refresh',True)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(self.tree.fontMetrics().height()+8)
        self.tree.currentItemChanged.connect(self.selected)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemDoubleClicked.connect(self.double_clicked)
        self.tree.itemExpanded.connect(self.expanded)
        self.tree.itemCollapsed.connect(lambda item: self.folder_icon(item,False))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        splitter.addWidget(self.tree)
        self.files = PlaylistFiles(); self.files.setMinimumHeight(self.files.fontMetrics().height()+8)
        self.files.model().rowsMoved.connect(self.reordered)
        self.files.filesDropped.connect(self.add_paths)
        self.files.playRequested.connect(self.play_file)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        files_panel=QWidget(); file_layout=QVBoxLayout(files_panel)
        file_layout.setContentsMargins(0,0,0,0)
        self.folder_label=QLabel(); file_layout.addWidget(self.folder_label); file_layout.addWidget(self.files)
        splitter.addWidget(files_panel); layout.addWidget(splitter, 1)
        self.file_error = QLabel()
        self.file_error.setTextFormat(Qt.TextFormat.PlainText)
        self.file_error.setWordWrap(True)
        self.file_error.hide()
        layout.addWidget(self.file_error)
        row = QHBoxLayout()
        self.add_button = QPushButton(tr('Ajouter des vidéos…')); self.add_button.clicked.connect(self.add_files); row.addWidget(self.add_button)
        self.remove_button = QPushButton(tr('Retirer de la liste')); self.remove_button.clicked.connect(self.remove_files); row.addWidget(self.remove_button)
        layout.addLayout(row)
        style_button(self.add_button,'plus'); style_button(self.remove_button,'minus',True)
        scroll.setMinimumWidth(230)
        self.rebuild()

    def run(self, operation):
        try: return operation()
        except (OSError, ValueError, KeyError, StopIteration) as error: self.w.error(str(error))

    def add_node(self, parent, title, data):
        item = QTreeWidgetItem(parent, [title]); item.setData(0, Qt.ItemDataRole.UserRole, data)
        if data:
            item.setIcon(0,icon('time' if data[0]=='temporary' else 'folder' if data[1] else 'list'))
        return item

    def folder_icon(self,item,opened):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if data and data[0]!='temporary' and data[1]:
            item.setIcon(0,icon('opened' if opened else 'folder'))

    def rebuild(self, select=None):
        self.rebuilding = True
        current = select or self.current
        with QSignalBlocker(self.tree):
            self.tree.clear()
            saved = self.add_node(self.tree, tr('Listes enregistrées'), None)
            followed = self.add_node(self.tree, tr('Dossiers suivis'), None)
            temporary = self.add_node(self.tree, tr('Temporaire'), None)
            self.temporary_group = temporary
            for group,symbol in ((saved,'list'),(followed,'library'),(temporary,'time')): group.setIcon(0,icon(symbol))
            selection = None
            for entry in self.store.entries if self.store else []:
                folder = entry.get('root')
                data = (entry['id'], folder)
                item = self.add_node(followed if folder else saved, entry['name'], data)
                if folder:
                    if has_subfolders(folder): self.add_node(item, '…', None)
                    item.setToolTip(0, folder)
                if current and current[0] == entry['id']: selection = item
            for record in self.temporary:
                item = self.add_node(temporary, record['name'], ('temporary', record['id']))
                if current == ('temporary', record['id']): selection = item
            for item in (saved, followed, temporary): item.setExpanded(True)
            if selection: self.tree.setCurrentItem(selection)
        self.rebuilding = False
        self.selected(self.tree.currentItem(), None)

    def selected(self, item, previous):
        if self.rebuilding: return
        self.current = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.show_files()
        if self.current and self.current[0] != 'temporary' and self.current[1]: self.browse()

    def expanded(self, item):
        self.folder_icon(item,True)
        if self.rebuilding: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] != 'temporary' and data[1]: self.browse(item=item)

    def double_clicked(self, item, column=0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            item.setExpanded(not item.isExpanded()); return
        if id(item) in self.scans:
            self.pending_open = data; return
        if self.w.job: return
        if data[0] != 'temporary' and data[1] and not self.store.files(*data):
            item.setExpanded(not item.isExpanded())
        else: self.open_current()

    def show_files(self):
        self.file_error.hide()
        self.rebuilding = True; self.files.clear()
        data = self.current; editable = bool(data and data[0] != 'temporary')
        self.refresh_button.setEnabled(editable)
        self.add_button.setEnabled(editable); self.remove_button.setEnabled(editable)
        self.files.setDragEnabled(editable); self.files.setAcceptDrops(editable)
        paths = []
        if editable: paths = self.store.files(*data)
        elif data:
            record = next((r for r in self.temporary if r['id'] == data[1]), None)
            if record: paths = [m['path'] for m in record['doc'].media.values()]
        for path in paths:
            item = QListWidgetItem(icon('film'), Path(path).name); item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path); self.files.addItem(item)
            if not Path(path).is_file(): item.setText(item.text() + ' — ' + tr('Introuvable'))
        current=self.tree.currentItem()
        self.folder_label.setText(f'{current.text(0)}  ·  {len(paths)}' if current and data else '')
        self.folder_label.setVisible(bool(current and data))
        self.open_button.setEnabled(bool(paths) or bool(data and data[0] == 'temporary'))
        self.rebuilding = False

    def browse(self, refresh=False, item=None):
        if not self.store: return
        item = item or self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data or data[0] == 'temporary': return
        identity, folder = data
        if not folder: self.show_files(); return
        token=id(item)
        if token in self.scans:
            self.scans[token]=(item,refresh or self.scans[token][1])
            return
        self.scans[token]=(item,refresh)
        def scan():
            try:
                dirs,files=scan_folder(folder)
                result=(dirs,files,{p for p in dirs if has_subfolders(p)})
                error=''
            except (OSError,ValueError) as exc:
                result,error=None,str(exc)
            try: self.scanFinished.emit(token,result,error)
            except RuntimeError: pass
        Thread(target=scan, name='Cadence library', daemon=True).start()

    def folder_scanned(self,token,result,error):
        item,refresh=self.scans.pop(token)
        if not isValid(item): return
        data=item.data(0,Qt.ItemDataRole.UserRole)
        identity,folder=data
        pending=self.pending_open==data
        if pending: self.pending_open=None
        if error:
            if self.current==data: self.file_error.setText(error); self.file_error.show()
            return
        directories,files,expandable=result
        def apply():
            self.store.scanned(identity, folder, files, refresh)
            existing = {item.child(i).data(0, Qt.ItemDataRole.UserRole): item.child(i) for i in range(item.childCount())}
            for key, child in list(existing.items()):
                if key is None or key[1] not in directories: item.removeChild(child)
            for directory in directories:
                if (identity, directory) not in existing:
                    child = self.add_node(item, self.store.folder_name(identity, directory), (identity, directory))
                    child.setToolTip(0, directory)
                    if directory in expandable: self.add_node(child, '…', None)
                elif directory not in expandable:
                    child = existing[(identity, directory)]
                    while child.childCount(): child.takeChild(0)
                elif not existing[(identity, directory)].childCount():
                    self.add_node(existing[(identity, directory)], '…', None)
            if self.current == data: self.show_files()
        self.run(apply)
        if pending and self.current==data: self.double_clicked(item)

    def create_menu(self):
        if self.w.job or not self.store: return
        menu = QMenu(self)
        menu.addAction(tr('Liste vide…'), self.new_list)
        menu.addAction(tr('Liste depuis des fichiers…'), self.list_from_files)
        menu.addAction(tr('Suivre un dossier…'), self.follow_folder)
        menu.exec(self.mapToGlobal(self.rect().topLeft()))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr('Ajouter des vidéos'), '',
            tr('Vidéos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.mpeg *.mts *.m2ts *.wmv *.gif)'))
        return paths

    def new_list(self, paths=()):
        if self.w.job or not self.store: return
        name, ok = QInputDialog.getText(self, tr('Nouvelle liste'), tr('Nom'))
        if ok and name.strip():
            identity = self.run(lambda: self.store.create(name, paths))
            if identity: self.rebuild((identity, None))

    def list_from_files(self):
        paths = self.choose_files()
        if paths: self.new_list(paths)

    def follow_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Suivre un dossier'))
        if not folder: return
        identity = self.run(lambda: self.store.create(Path(folder).name, root=folder))
        if identity: self.rebuild((identity, folder))

    def selected_paths(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]

    def all_paths(self):
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]

    def add_files(self):
        if not self.w.job: self.add_paths(self.choose_files())

    def add_paths(self, paths):
        if self.w.job or not self.current or self.current[0] == 'temporary': return
        paths = [p for p in paths if Path(p).is_file() and Path(p).suffix.lower() in VIDEO_EXTENSIONS]
        if not paths: return
        identity, folder = self.current
        def success(added):
            self.run(lambda: self.store.set_files(identity, self.store.files(identity, folder) + added, folder))
            if self.current == (identity, folder): self.show_files()
        if folder:
            self.w.begin_task('Copie des vidéos', lambda p, c: copy_into_folder(paths, folder, p, c), success)
        else: success(paths)

    def reordered(self, *args):
        if self.rebuilding or not self.current or self.current[0] == 'temporary': return
        identity, folder = self.current
        if self.w.job: self.show_files(); return
        self.run(lambda: self.store.set_files(identity, self.all_paths(), folder))

    def remove_files(self):
        if self.w.job or not self.current or self.current[0] == 'temporary': return
        removed = self.selected_paths(); keys = {path_key(p) for p in removed}
        identity, folder = self.current
        self.run(lambda: self.store.set_files(identity, [p for p in self.all_paths() if path_key(p) not in keys], folder, removed))
        self.show_files()

    def trash_files(self):
        if self.w.job or not self.current or self.current[0] == 'temporary': return
        paths = self.selected_paths()
        if not paths: return
        text = tr('Mettre les fichiers sélectionnés à la corbeille ? Ils ne seront plus disponibles pour les autres listes et projets.')
        if QMessageBox.question(self, tr('Corbeille'), text + '\n\n' + '\n'.join(paths),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes: return
        removed = []
        for path in paths:
            ok, _ = QFile.moveToTrash(path)
            if ok: removed.append(path)
            else: self.w.error(tr('Impossible de mettre ce fichier à la corbeille :') + '\n' + path)
        identity, folder = self.current
        self.run(lambda: self.store.set_files(identity, [p for p in self.all_paths() if p not in removed], folder, removed))
        self.show_files()

    def files_menu(self, point):
        item = self.files.itemAt(point)
        if not item or self.w.job or not self.current or self.current[0] == 'temporary': return
        if not item.isSelected(): self.files.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(tr('Retirer de la liste'), self.remove_files)
        if len(self.files.selectedItems()) == 1: menu.addAction(tr('Remplacer le chemin…'), self.relocate_file)
        menu.addAction(tr('Afficher dans l’explorateur'), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.data(Qt.ItemDataRole.UserRole)).parent))))
        menu.addSeparator(); menu.addAction(tr('Mettre à la corbeille…'), self.trash_files)
        menu.exec(self.files.mapToGlobal(point))

    def relocate_file(self):
        if self.w.job or not self.current or self.current[0] == 'temporary': return
        selected = self.selected_paths()
        if len(selected) != 1: return
        replacement, _ = QFileDialog.getOpenFileName(self, tr('Retrouver la vidéo'), '',
            tr('Vidéos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.mpeg *.mts *.m2ts *.wmv *.gif)'))
        if not replacement: return
        identity, folder = self.current; previous = selected[0]; paths = self.all_paths()
        def success(copied):
            self.run(lambda: self.store.set_files(identity, [copied[0] if p == previous else p for p in paths], folder, [previous]))
            if self.current == (identity, folder): self.show_files()
        if folder:
            self.w.begin_task('Copie des vidéos', lambda p, c: copy_into_folder([replacement], folder, p, c), success)
        else: success([replacement])

    def tree_menu(self, point):
        item = self.tree.itemAt(point)
        if not item or self.w.job: return
        self.tree.setCurrentItem(item)
        data = self.current
        if not data: return
        menu = QMenu(self); menu.addAction(tr('Ouvrir'), self.open_current).setEnabled(self.open_button.isEnabled())
        menu.addAction(tr('Renommer la liste…'), self.rename)
        if data[0] != 'temporary':
            entry = self.store.entry(data[0])
            if data[1] is None or path_key(data[1]) == path_key(entry['root']):
                menu.addAction(tr('Retirer de la bibliothèque'), self.remove_entry)
            if data[1]: menu.addAction(tr('Actualiser'), lambda: self.browse(refresh=True))
        else: menu.addAction(tr('Retirer de la bibliothèque'), self.remove_temporary)
        menu.exec(self.tree.mapToGlobal(point))

    def rename(self):
        if not self.current or self.w.job: return
        identity, folder = self.current
        item = self.tree.currentItem()
        name, ok = QInputDialog.getText(self, tr('Renommer la liste'), tr('Nom'), text=item.text(0))
        if ok and name.strip():
            if identity == 'temporary':
                record = next((r for r in self.temporary if r['id'] == folder), None)
                if record: record['name'] = name.strip(); item.setText(0, name.strip())
            else:
                def apply():
                    self.store.rename(identity, name, folder); item.setText(0, name.strip())
                self.run(apply)

    def remove_temporary(self):
        if not self.current or self.current[0] != 'temporary' or self.w.job: return
        self.temporary = [r for r in self.temporary if r['id'] != self.current[1]]
        self.current = None; self.rebuild()

    def remove_entry(self):
        self.run(lambda: self.store.remove(self.current[0])); self.current = None; self.rebuild()

    def archive_current(self):
        w = self.w; doc = w.doc
        if not doc.media and not doc.state.drawings: return
        w.drawing.finish(); w.commit_exposure(); w.clip_tools.commit()
        doc.review = w.comparison_snapshot()
        self.serial += 1
        name = Path(doc.project_path).stem if doc.project_path else next((m['name'] for m in doc.media.values()), tr('Montage'))
        self.temporary.append(dict(id=self.serial, name=f'{self.serial}. {name} · {datetime.now():%H:%M:%S}', doc=doc,
                                   zoom=w.timeline.zoom, start=w.timeline.view_start))
        self.add_node(self.temporary_group, self.temporary[-1]['name'], ('temporary', self.serial))

    def play_file(self, path):
        if self.w.job: return
        self.open_paths([path], autoplay=True)

    def show_file_error(self, message):
        self.file_error.setText(tr(message))
        self.file_error.show()

    def start_file_playback(self):
        doc = self.pending_playback
        if doc is self.w.doc and self.w.job: return
        self.play_timer.stop(); self.pending_playback = None
        if doc is self.w.doc and not self.w.transport.running:
            self.w.toggle_play()

    def open_current(self):
        if self.w.job or not self.current: return
        identity, folder = self.current; w = self.w
        if identity == 'temporary':
            record = next((r for r in self.temporary if r['id'] == folder), None)
            if not record: return
            self.archive_current(); self.temporary.remove(record)
            w.install_doc(record['doc']); w.timeline.zoom = record['zoom']; w.timeline.view_start = record['start']
            w.sync_timeline_scroll(); self.current = None; self.rebuild(); return
        paths = self.store.files(identity, folder)
        self.open_paths(paths)

    def open_paths(self, paths, autoplay=False):
        w = self.w
        if w.job: return
        if not paths: return
        self.file_error.hide()
        report_error = self.show_file_error if autoplay else w.error
        missing = [p for p in paths if not Path(p).is_file()]
        if missing:
            report_error(tr('Vidéos introuvables. Actualisez le dossier ou corrigez les chemins avant d’ouvrir la liste.') + '\n\n' + '\n'.join(missing)); return
        quality = w.preferences.get('preview_quality', 'native')
        def prepare(progress, cancel):
            from media import prepare_batch
            from model import Document
            items = prepare_batch(paths, None, progress, cancel, quality=quality, defer_audio=True)
            doc = Document(Fraction(items[0]['fps'])); doc.append_media(items); doc.undo_stack.clear()
            if autoplay: doc.saved_signature = doc.signature()
            return doc
        def success(doc):
            self.archive_current(); w.install_doc(doc); w.timeline.reset_view(); w.viewer.reset_view()
            if autoplay:
                self.pending_playback = doc; self.play_timer.start()
            else: self.rebuild()
        title = 'Préparation du média' if len(paths)==1 else 'Ouverture de la liste'
        w.begin_media_open(paths, title, prepare, success, report_error)
