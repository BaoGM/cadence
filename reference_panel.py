# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from PySide6.QtCore import Qt,Signal,QEvent,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QListWidget,QListWidgetItem,QAbstractItemView,QPushButton,QMenu
from reference_sequence import ReferenceSequence
from ui_text import tr


class ReferenceList(QListWidget):
    reordered=Signal()
    deleteRequested=Signal()

    def dropEvent(self,event):
        super().dropEvent(event)
        self.reordered.emit()

    def event(self,event):
        if event.type()==QEvent.Type.ShortcutOverride and event.key()==Qt.Key.Key_Delete:
            event.accept(); return True
        return super().event(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Delete:
            self.deleteRequested.emit(); event.accept()
        else: super().keyPressEvent(event)


class ReferenceQueueMixin:
    def build_reference_list(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(0,6,0,0)
        self.reference_list=ReferenceList(); self.reference_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.reference_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.reference_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.reference_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.reference_list.customContextMenuRequested.connect(self.reference_context)
        self.reference_list.reordered.connect(self.reference_reordered)
        self.reference_list.deleteRequested.connect(self.remove_reference_items)
        self.reference_list.itemDoubleClicked.connect(self.seek_reference)
        layout.addWidget(self.reference_list)
        add=QPushButton(tr('Ajouter des références…')); add.clicked.connect(self.open_reference); layout.addWidget(add)
        self.reference_tab=self.library_tabs.addTab(page,tr('Références'))

    def reference_entries(self):
        pool={**self.doc.media,**self.reference_sources}
        entries=[pool[key] for key in self.reference_order if key in pool]
        return entries or ([self.compare_media] if self.compare_media else [])

    def rebuild_reference_index(self):
        self.reference_index=ReferenceSequence(self.reference_entries())
        self.refresh_reference_queue()

    def refresh_reference_queue(self):
        with QSignalBlocker(self.reference_list):
            self.reference_list.clear()
            for index,media in enumerate(self.reference_entries()):
                name=media['name']+(tr(' · indisponible') if media.get('available') is False else '')
                item=QListWidgetItem(f'{index+1}. {name}'); item.setData(Qt.ItemDataRole.UserRole,index)
                item.setToolTip(media['path']); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsDropEnabled)
                self.reference_list.addItem(item)

    def set_reference_sequence(self,entries,append=False):
        entries=(self.reference_entries() if append else [])+list(entries)
        for media in entries: self.reference_sources[media['id']]=media
        self.reference_order=[media['id'] for media in entries]
        self.compare_media=entries[0] if entries else None
        self.rebuild_reference_index(); self.reference_signature=None; self.refresh_reference_choices()
        self.viewer.reference_rgb=None
        with QSignalBlocker(self.compare_enabled): self.compare_enabled.setChecked(bool(entries))
        self.comparison_changed()
        self.doc.review=self.comparison_snapshot()
        self.refresh()

    def reference_reordered(self):
        old=self.reference_entries()
        order=[self.reference_list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.reference_list.count())]
        self.set_reference_sequence([old[index] for index in order])

    def remove_reference_items(self):
        selected={item.data(Qt.ItemDataRole.UserRole) for item in self.reference_list.selectedItems()}
        if selected: self.set_reference_sequence([media for index,media in enumerate(self.reference_entries()) if index not in selected])

    def move_reference_items(self,step):
        selected={self.reference_list.row(item) for item in self.reference_list.selectedItems()}
        entries=self.reference_entries(); order=list(range(len(entries)))
        for row in sorted(selected,reverse=step>0):
            other=row+step
            if 0<=other<len(order) and other not in selected:
                order[row],order[other]=order[other],order[row]; selected.remove(row); selected.add(other)
        self.set_reference_sequence([entries[index] for index in order])
        for row in selected: self.reference_list.item(row).setSelected(True)

    def reference_context(self,point):
        item=self.reference_list.itemAt(point)
        if item and not item.isSelected(): self.reference_list.setCurrentItem(item)
        menu=QMenu(self.reference_list); menu.addAction(tr('Ajouter des références…'),self.open_reference)
        if self.reference_list.selectedItems():
            menu.addSeparator(); menu.addAction(tr('Monter'),lambda:self.move_reference_items(-1)); menu.addAction(tr('Descendre'),lambda:self.move_reference_items(1))
            menu.addSeparator(); menu.addAction(tr('Supprimer'),self.remove_reference_items)
        menu.exec(self.reference_list.mapToGlobal(point)); menu.deleteLater()

    def seek_reference(self,item):
        index=item.data(Qt.ItemDataRole.UserRole)
        seconds=self.reference_index.ends[index-1] if index else Fraction(0)
        self.seek(max(0,min(self.doc.state.length-1,round(seconds*self.doc.fps)-self.compare_offset.value())))
