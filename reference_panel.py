# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from library_style import (icon, style_button, media_details, SourceRows, LibrarySplitter, panel_strip, panel_heading,
                           TITLE_ROLE, DETAIL_ROLE, POSTER_ROLE, EmptyHint, set_preview)
from PySide6.QtGui import QImage,QPixmap,QIcon
from PySide6.QtCore import Qt,Signal,QEvent,QSignalBlocker,QByteArray
from PySide6.QtWidgets import QWidget,QVBoxLayout,QListWidget,QListWidgetItem,QAbstractItemView,QPushButton,QMenu,QLabel,QScrollArea
from model import locate
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
    def build_reference_list(self, controls):
        page=QWidget(); page.setObjectName('studioPage'); layout=QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        self.ref_thumbnails={}
        self.reference_split=split=LibrarySplitter(Qt.Vertical); split.setChildrenCollapsible(False); split.setHandleWidth(6)
        layout.addWidget(split)
        queue=QWidget(); split.addWidget(queue); layout=QVBoxLayout(queue); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        header=panel_strip(layout)
        source_label=QLabel('B'); source_label.setToolTip(tr('Source B')); source_label.setBuddy(self.reference_combo)
        source_label.setAlignment(Qt.AlignCenter); source_label.setFixedWidth(18); header.addWidget(source_label)
        self.reference_combo.setAccessibleName(tr('Source B')); header.addWidget(self.reference_combo,1)
        self.ref_caption,self.ref_count=panel_heading(panel_strip(layout,'heading'),tr('Ordre de comparaison'))
        self.reference_list=ReferenceList(); self.reference_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.reference_list.setItemDelegate(SourceRows(self.reference_list,ordered=True,thumbnails=self.source_previews))
        self.reference_list.empty_hint=EmptyHint(self.reference_list,tr('Ajoutez une référence pour comparer les images.'))
        self.reference_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.reference_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.reference_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.reference_list.customContextMenuRequested.connect(self.reference_context)
        self.reference_list.reordered.connect(self.reference_reordered)
        self.reference_list.deleteRequested.connect(self.remove_reference_items)
        self.reference_list.itemDoubleClicked.connect(self.seek_reference)
        layout.addWidget(self.reference_list,1)
        self.track_ref_readout=QListWidget(); self.track_ref_readout.setItemDelegate(SourceRows(self.track_ref_readout,ordered=True,thumbnails=self.source_previews))
        self.track_ref_readout.hide(); self.track_ref_signature=None; layout.addWidget(self.track_ref_readout,1)
        footer=panel_strip(layout,'footer')
        footer.addWidget(self.compare_enabled)
        footer.addStretch()
        add=style_button(QPushButton(tr('Ajouter des références…')),'plus',True); add.clicked.connect(self.open_reference); footer.addWidget(add)
        self.ref_buttons=[]
        for label,direction,symbol in [('Monter',-1,'up'),('Descendre',1,'down')]:
            button=style_button(QPushButton(tr(label)),symbol,True); self.ref_buttons.append(button)
            button.clicked.connect(lambda checked=False, step=direction:self.move_reference_items(step)); footer.addWidget(button)
        self.reference_list.itemSelectionChanged.connect(self.ref_button_state)
        self.ref_button_state()
        self.reference_list.setMinimumHeight(42); self.track_ref_readout.setMinimumHeight(42)
        controls.setMinimumHeight(88)
        split.addWidget(controls); split.setSizes([270,190]); split.setStretchFactor(0,1)
        saved=self.settings.value('library/reference_split')
        if isinstance(saved,QByteArray): split.restoreState(saved)
        split.splitterMoved.connect(lambda *_:self.settings.setValue('library/reference_split',split.saveState()))
        container=QScrollArea()
        container.setFrameShape(QScrollArea.NoFrame); container.setWidgetResizable(True)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); container.setWidget(page)
        self.reference_tab=self.library_tabs.addTab(container,tr('Références'))
        for i in range(self.library_tabs.count()):
            self.library_tabs.setTabToolTip(i,self.library_tabs.tabText(i))
            self.library_tabs.tabBar().setAccessibleTabName(i,self.library_tabs.tabText(i))

    def ref_button_state(self):
        rows={self.reference_list.row(item) for item in self.reference_list.selectedItems()}
        for step,button in zip((-1,1),self.ref_buttons):
            button.setEnabled(any(0<=i+step<self.reference_list.count() and i+step not in rows for i in rows))

    def sync_panel_source(self):
        identity=getattr(self,'reference_track_id',None)
        self.reference_list.setVisible(not bool(identity))
        self.track_ref_readout.setVisible(bool(identity))
        self.refresh_track_reference(self.doc.state.position)
        self.ref_count.setVisible(not identity)
        for button in self.ref_buttons: button.setVisible(not bool(identity))

    def refresh_track_reference(self,frame):
        identity=getattr(self,'reference_track_id',None)
        if not identity: return
        track=next((track for track in self.doc.state.tracks if track.info.id==identity),None)
        key=None
        if track:
            frame+=self.compare_offset.value()
            if 0<=frame<track.length: key=locate(track.segments,frame)[0]
        signature=(identity,key,self.doc.media.get(key,{}).get('name'),track.info.name if track else '')
        if signature==self.track_ref_signature: return
        self.track_ref_signature=signature; self.track_ref_readout.clear()
        media=self.doc.media.get(key)
        if media:
            item=QListWidgetItem(icon('film'),media['name']); item.setToolTip(media['path'])
            set_preview(item,media)
            item.setData(DETAIL_ROLE,tr(track.info.name))
        else:
            item=QListWidgetItem(tr('Aucun média à cette image.'))
        self.track_ref_readout.addItem(item)

    def remember_thumbnail(self,key,array):
        if key in self.ref_thumbnails or array is None: return
        h,w=array.shape[:2]
        image=QImage(array.data,w,h,array.strides[0],QImage.Format.Format_RGB888)
        small=QPixmap.fromImage(image.scaled(56,36,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        self.ref_thumbnails[key]=QIcon(small)
        for i,media in enumerate(self.reference_entries()):
            if media['id']==key and self.reference_list.item(i):
                self.reference_list.item(i).setIcon(self.ref_thumbnails[key]); self.reference_list.item(i).setData(POSTER_ROLE,True)

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
                details=media_details(media)
                item=QListWidgetItem(self.ref_thumbnails.get(media['id'],icon('film')),f'{index+1}. {name}'+('\n'+details if details else '')); item.setData(Qt.ItemDataRole.UserRole,index)
                item.setData(TITLE_ROLE,name); item.setData(DETAIL_ROLE,f'{index+1} · {details}' if details else str(index+1))
                item.setData(POSTER_ROLE,media['id'] in self.ref_thumbnails)
                set_preview(item,media)
                item.setToolTip(media['path']); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsDropEnabled)
                self.reference_list.addItem(item)
        self.ref_count.setText(str(self.reference_list.count())); self.ref_button_state()
        self.ref_thumbnails={k:v for k,v in self.ref_thumbnails.items() if k in self.reference_order}

    def set_reference_sequence(self,entries,append=False):
        self.reference_track_id=None
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
