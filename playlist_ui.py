# SPDX-License-Identifier: GPL-3.0-only
from datetime import datetime
import json
from fractions import Fraction
from threading import Thread
from library_style import (icon, style_button, panel_strip, panel_heading, LibrarySplitter, LibraryTree,
                           TreeRows, SourceRows, SYMBOL_ROLE, EmptyHint, set_preview)
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QFile, QSignalBlocker, QEvent, QMimeData, QItemSelectionModel
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from shiboken6 import isValid
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
                              QListWidget, QListWidgetItem, QAbstractItemView, QPushButton,
                              QMenu, QFileDialog, QInputDialog, QMessageBox, QSplitter,
                              QScrollArea, QLayout, QLabel)

from playlist_store import PlaylistStore, scan_folder, has_subfolders, copy_into_folder, canonical, path_key, VIDEO_EXTENSIONS
from ui_text import tr

LIBRARY_MIME='application/x-cadence-library'


class PlaylistTree(LibraryTree):
    def mimeTypes(self):
        return [LIBRARY_MIME]

    def mimeData(self,items):
        nodes=[item.data(0,Qt.UserRole) for item in items if item.data(0,Qt.UserRole)]
        data=QMimeData()
        if nodes: data.setData(LIBRARY_MIME,json.dumps(dict(node=nodes[0])).encode())
        return data


class PlaylistFiles(QListWidget):
    filesDropped = Signal(list)
    playRequested = Signal(list)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.pressed_selection=None

    def mousePressEvent(self,event):
        self.pressed_selection=None
        item=self.itemAt(event.position().toPoint())
        if (item and item.isSelected() and event.button()==Qt.LeftButton and event.modifiers()==Qt.NoModifier
                and len(self.selectedIndexes())>1):
            self.pressed_selection=item,self.selectionModel().selection()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        group=self.pressed_selection
        self.pressed_selection=None
        if item and item.isSelected() and len(self.selectedIndexes())>1:
            group=item,self.selectionModel().selection()
        super().mouseDoubleClickEvent(event)
        if item and event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if group and group[0] is item:
                self.selectionModel().select(group[1],QItemSelectionModel.ClearAndSelect)
                paths=[selected.data(Qt.UserRole) for selected in sorted(self.selectedItems(),key=self.row)]
            else: paths=[item.data(Qt.UserRole)]
            self.playRequested.emit(paths)

    def startDrag(self, actions):
        super().startDrag(actions | Qt.CopyAction)

    def mimeData(self,items):
        data=super().mimeData(items)
        paths=[item.data(Qt.UserRole) for item in sorted(items,key=self.row)]
        data.setData(LIBRARY_MIME,json.dumps(dict(paths=paths)).encode())
        return data

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
        content = QWidget(); content.setObjectName('studioPage'); scroll.setWidget(content); outer.addWidget(scroll)
        layout = QVBoxLayout(content); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        row = panel_strip(layout)
        new = QPushButton(tr('Nouveau…')); new.clicked.connect(self.create_menu); row.addWidget(new)
        self.open_button = QPushButton(tr('Ouvrir')); self.open_button.clicked.connect(self.open_current); row.addWidget(self.open_button)
        row.addStretch(); self.refresh_button = QPushButton(tr('Actualiser')); self.refresh_button.clicked.connect(lambda: self.browse(refresh=True)); row.addWidget(self.refresh_button)
        style_button(new,'plus'); style_button(self.open_button,'open'); style_button(self.refresh_button,'refresh',True)
        splitter = LibrarySplitter(Qt.Orientation.Vertical); splitter.setHandleWidth(6); splitter.setChildrenCollapsible(False)
        self.tree = PlaylistTree(); self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setDefaultDropAction(Qt.CopyAction)
        self.tree.setItemDelegate(TreeRows(self.tree)); self.tree.setIndentation(13); self.tree.setMouseTracking(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.currentItemChanged.connect(self.selected)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemDoubleClicked.connect(self.double_clicked)
        self.tree.itemExpanded.connect(self.expanded)
        self.tree.itemCollapsed.connect(lambda item: self.folder_icon(item,False))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        splitter.addWidget(self.tree)
        self.files = PlaylistFiles()
        self.files.setItemDelegate(SourceRows(self.files,thumbnails=window.source_previews)); self.empty_files=EmptyHint(self.files,'')
        self.files.model().rowsMoved.connect(self.reordered)
        self.files.filesDropped.connect(self.add_paths)
        self.files.playRequested.connect(self.open_selected_files)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        files_panel=QWidget(); file_layout=QVBoxLayout(files_panel)
        file_layout.setContentsMargins(0,0,0,0); file_layout.setSpacing(0)
        self.folder_label,self.folder_count=panel_heading(panel_strip(file_layout,'heading'),'')
        file_layout.addWidget(self.files,1)
        splitter.addWidget(files_panel); layout.addWidget(splitter, 1)
        splitter.setStretchFactor(0,0); splitter.setStretchFactor(1,1); splitter.setSizes([164,225])
        self.file_error = QLabel()
        self.file_error.setTextFormat(Qt.TextFormat.PlainText)
        self.file_error.setWordWrap(True)
        self.file_error.hide()
        layout.addWidget(self.file_error)
        row = panel_strip(layout,'footer'); self.file_footer=row.parentWidget()
        self.add_button = QPushButton(tr('Ajouter des vidéos…')); self.add_button.clicked.connect(self.add_files); row.addWidget(self.add_button)
        self.remove_button = QPushButton(tr('Retirer de la liste')); self.remove_button.clicked.connect(self.remove_files); row.addWidget(self.remove_button)
        row.insertStretch(1)
        style_button(self.add_button,'plus'); style_button(self.remove_button,'minus',True)
        scroll.setMinimumWidth(204); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.open_button_maximum=self.open_button.maximumWidth()
        self.header_viewport=scroll.viewport()
        self.header_viewport.installEventFilter(self)
        self.rebuild()

    def showEvent(self, event):
        super().showEvent(event)
        for view in (self.tree, self.files):
            margins = view.contentsMargins()
            row_height = max(view.itemDelegate().row_height, view.fontMetrics().height() + 8)
            view.setMinimumHeight(row_height + margins.top() + margins.bottom())

    def eventFilter(self,obj,event):
        if obj is self.header_viewport and event.type()==QEvent.Type.Resize:
            narrow=obj.width()<235
            self.open_button.setText('' if narrow else tr('Ouvrir'))
            if narrow: self.open_button.setFixedWidth(30)
            else:
                self.open_button.setMinimumWidth(0); self.open_button.setMaximumWidth(self.open_button_maximum)
        return super().eventFilter(obj,event)

    def run(self, operation):
        try: return operation()
        except (OSError, ValueError, KeyError, StopIteration) as error: self.w.error(str(error))

    def add_node(self, parent, title, data):
        item = QTreeWidgetItem(parent, [title]); item.setData(0, Qt.ItemDataRole.UserRole, data)
        if data:
            symbol='time' if data[0]=='temporary' else 'folder' if data[1] else 'list'
            item.setIcon(0,icon(symbol)); item.setData(0,SYMBOL_ROLE,symbol)
        else:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
        return item

    def folder_icon(self,item,opened):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if data and data[0]!='temporary' and data[1]:
            symbol='opened' if opened else 'folder'
            item.setIcon(0,icon(symbol)); item.setData(0,SYMBOL_ROLE,symbol)

    def rebuild(self, select=None):
        self.rebuilding = True
        current = select or self.current
        expanded={self.tree.topLevelItem(i).text(0):self.tree.topLevelItem(i).isExpanded()
                  for i in range(self.tree.topLevelItemCount())}
        with QSignalBlocker(self.tree):
            self.tree.clear()
            followed = self.add_node(self.tree, tr('Dossiers suivis'), None)
            saved = self.add_node(self.tree, tr('Listes enregistrées'), None)
            temporary = self.add_node(self.tree, tr('Temporaire'), None)
            self.temporary_group = temporary
            for group,symbol in ((saved,'list'),(followed,'library'),(temporary,'time')):
                group.setIcon(0,icon(symbol)); group.setData(0,SYMBOL_ROLE,symbol)
            selection = None
            for entry in self.store.entries if self.store else []:
                folder = entry.get('root')
                data = (entry['id'], folder)
                item = self.add_node(followed if folder else saved, entry['name'], data)
                if folder:
                    if has_subfolders(folder,entry['folders'].get(folder,{}).get('excluded_folders',())): self.add_node(item, '…', None)
                    item.setToolTip(0, folder)
                if current and current[0] == entry['id']: selection = item
            for record in self.temporary:
                item = self.add_node(temporary, record['name'], ('temporary', record['id']))
                if current == ('temporary', record['id']): selection = item
            for group in (followed,saved,temporary): group.setExpanded(expanded.get(group.text(0),group is followed))
            if selection:
                selection.parent().setExpanded(True); self.tree.setCurrentItem(selection)
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
        self.file_footer.setVisible(editable)
        self.refresh_button.setEnabled(editable)
        self.add_button.setEnabled(editable); self.remove_button.setEnabled(editable)
        self.files.setDragEnabled(bool(data)); self.files.setAcceptDrops(editable)
        paths = []
        if editable: paths = self.store.files(*data)
        elif data:
            record = next((r for r in self.temporary if r['id'] == data[1]), None)
            if record: paths = self.temporary_paths(record)
        for path in paths:
            item = QListWidgetItem(icon('film'), Path(path).name); item.setData(Qt.ItemDataRole.UserRole, path)
            set_preview(item,dict(path=path))
            item.setToolTip(path); self.files.addItem(item)
            if not Path(path).is_file(): item.setText(item.text() + ' — ' + tr('Introuvable'))
        self.empty_files.setText(tr('Aucun fichier dans ce dossier.') if editable and data[1] else
                                 tr('Aucun fichier dans cette liste.') if data else tr('Sélectionnez un dossier ou une liste.'))
        self.empty_files.refresh()
        current=self.tree.currentItem()
        self.folder_label.setText(current.text(0) if current and data else '')
        self.folder_label.setToolTip(self.folder_label.text()); self.folder_count.setText(f"{len(paths)} {tr('fichier') if len(paths)==1 else tr('fichiers')}")
        self.folder_label.parentWidget().setVisible(bool(current and data))
        self.open_button.setEnabled(bool(paths) or bool(data and data[0] == 'temporary'))
        self.rebuilding = False

    @staticmethod
    def temporary_paths(record,*,with_keys=False):
        occurrences={}
        doc=record['doc']
        for lane,track in enumerate(doc.state.tracks):
            for segments in (track.segments,track.audio):
                frame=0
                for segment in segments:
                    if segment.media in doc.media:
                        occurrences[frame,lane,segment.media]=doc.media[segment.media]['path']
                    frame+=segment.length
        excluded=record.get('hidden_paths',())
        keys=[key for key in sorted(occurrences,key=lambda key:key[:2]) if key not in excluded]
        return keys if with_keys else [occurrences[key] for key in keys]

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
        records=self.store.entry(identity)['folders']
        def scan():
            try:
                dirs,files=scan_folder(folder)
                result=(dirs,files,{p for p in dirs if has_subfolders(p,records.get(p,{}).get('excluded_folders',()))})
                error=''
            except (OSError,ValueError) as exc:
                result,error=None,str(exc)
            try: self.scanFinished.emit(token,result,error)
            except RuntimeError: pass
        Thread(target=scan, name='Cadence library', daemon=True).start()

    def folder_scanned(self,token,result,error):
        item,refresh=self.scans.pop(token)
        if not isValid(item) or item.treeWidget() is not self.tree: return
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
            hidden={path_key(p) for p in self.store.entry(identity)['folders'][canonical(folder)].get('excluded_folders',())}
            visible=[directory for directory in directories if path_key(directory) not in hidden]
            existing = {item.child(i).data(0, Qt.ItemDataRole.UserRole): item.child(i) for i in range(item.childCount())}
            for key, child in list(existing.items()):
                if key is None or key[1] not in visible: item.removeChild(child)
            for directory in visible:
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
        if self.w.job or not self.current: return
        removed = self.selected_paths(); keys = {path_key(p) for p in removed}
        identity, folder = self.current
        if identity=='temporary':
            record=next((r for r in self.temporary if r['id']==folder),None)
            if record:
                row_ids=self.temporary_paths(record,with_keys=True)
                record.setdefault('hidden_paths',set()).update(row_ids[self.files.row(item)] for item in self.files.selectedItems())
                self.show_files()
            return
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
        if not item or self.w.job or not self.current: return
        if not item.isSelected(): self.files.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(tr('Retirer de la liste'), self.remove_files)
        if self.current[0]=='temporary':
            menu.exec(self.files.mapToGlobal(point)); return
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
        if item.isSelected() and len(self.tree.selectedItems())>1:
            menu=QMenu(self)
            menu.addAction(tr('Retirer de la bibliothèque'),self.remove_selected_entries)
            menu.exec(self.tree.mapToGlobal(point))
            return
        self.tree.setCurrentItem(item)
        data = self.current
        if not data: return
        menu = QMenu(self); menu.addAction(tr('Ouvrir'), self.open_current).setEnabled(self.open_button.isEnabled())
        menu.addAction(tr('Renommer la liste…'), self.rename)
        if data[0] != 'temporary':
            menu.addAction(tr('Retirer de la bibliothèque'), self.remove_selected_entries)
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

    def remove_selected_entries(self):
        if self.w.job: return
        items=[item for item in self.tree.selectedItems() if item.data(0,Qt.UserRole)]
        if not items: return
        nodes=[item.data(0,Qt.UserRole) for item in items]
        saved=[node for node in nodes if node[0]!='temporary']
        def remove():
            if saved: self.store.remove_nodes(saved)
            temporary={folder for identity,folder in nodes if identity=='temporary'}
            self.temporary=[rec for rec in self.temporary if rec['id'] not in temporary]
            with QSignalBlocker(self.tree):
                for item in items:
                    if item.treeWidget() is self.tree: item.parent().removeChild(item)
            self.selected(self.tree.currentItem(),None)
        self.run(remove)

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

    def open_selected_files(self,paths):
        if not paths or self.w.job: return
        if len(paths)==1: self.play_file(paths[0])
        else:
            track=self.w.doc.active_track
            self.w.media_source_drops.insert_library(dict(paths=paths),track.info.id,track.length,autoplay=True)

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
