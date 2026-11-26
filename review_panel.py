# SPDX-License-Identifier: GPL-3.0-only
import csv
from bisect import bisect_right
from dataclasses import dataclass, replace
from fractions import Fraction
from heapq import heappop, heappush
from pathlib import Path
from weakref import ref

from PySide6.QtCore import Qt, QSignalBlocker, QEvent, QByteArray, QRect, QSize
from PySide6.QtGui import QIcon, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QToolButton,
                               QStackedWidget, QSizePolicy, QToolTip, QListView, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget, QInputDialog, QMessageBox)

from library_style import DETAIL_ROLE, TITLE_ROLE, LibrarySplitter, icon, style_button
from model import State
from review_editor import BOLD, ITALIC, UNDERLINE, STRIKE, ReviewEditor
from review_format import frame_ranges
from review_csv import load_csv, map_rows, merge_rows, source_fps, write_csv
from review_otio import read_otio, write_otio
from ui_text import tr


def active_intervals(frames, notes):
    bounds={}
    for frame in frames:
        end=frame+notes.get(frame,(1,''))[0]
        bounds[frame]=end
        bounds.setdefault(end,None)
    active=[]
    times=sorted(bounds)
    owners=[]
    for point in times:
        if bounds[point] is not None:
            heappush(active,(-point,bounds[point]))
        while active and active[0][1]<=point:
            heappop(active)
        owners.append(-active[0][0] if active else None)
    return times,owners


class CommentExportDialog(QFileDialog):
    def __init__(self, parent, rendered_media=None, *, folder='', source_hint=''):
        super().__init__(parent,tr('Exporter les commentaires…'),str(rendered_media.parent) if rendered_media else folder)
        self.setOption(QFileDialog.DontUseNativeDialog)
        self.formats={tr('Commentaires CSV (*.csv)'):'csv',tr('Marqueurs OpenTimelineIO (*.otio)'):'otio'}
        self.setAcceptMode(QFileDialog.AcceptSave)
        self.setNameFilters(list(self.formats))
        self.setDefaultSuffix('csv')
        self.filterSelected.connect(self.change_format)
        self.movie_row=None
        self.source_hint=source_hint
        if rendered_media:
            self.selectFile(rendered_media.with_suffix('.csv').name)
        else:
            self.movie_row=QWidget(self)
            row=QHBoxLayout(self.movie_row)
            row.setContentsMargins(0,0,0,0)
            label=QLabel(tr('Vidéo'))
            self.movie=QLineEdit()
            self.movie.setAccessibleName(tr('Choisir la vidéo du montage pour OpenTimelineIO'))
            label.setBuddy(self.movie)
            browse=QPushButton(tr('Parcourir…'))
            browse.setAutoDefault(False)
            browse.clicked.connect(self.choose_movie)
            row.addWidget(label)
            row.addWidget(self.movie,1)
            row.addWidget(browse)
            grid=self.layout()
            grid.addWidget(self.movie_row,grid.rowCount(),0,1,grid.columnCount())
            self.movie_row.hide()

    def choose_movie(self):
        movie,_=QFileDialog.getOpenFileName(self,tr('Choisir la vidéo du montage pour OpenTimelineIO'),self.movie.text() or self.source_hint)
        if movie:
            self.movie.setText(movie)
        return bool(movie)

    def change_format(self,label):
        suffix=self.formats[label]
        self.setDefaultSuffix(suffix)
        if self.movie_row is not None:
            self.movie_row.setVisible(suffix=='otio')
        edit=self.findChild(QLineEdit,'fileNameEdit')
        if edit is not None and edit.text():
            name=Path(edit.text())
            if name.suffix.lower()[1:] in self.formats.values():
                edit.setText(str(name.with_suffix('.'+suffix)))

    @classmethod
    def destination(cls,parent,rendered_media=None,**options):
        dialog=cls(parent,rendered_media,**options)
        try:
            if dialog.exec()==QDialog.Accepted:
                path=Path(dialog.selectedFiles()[0]).absolute()
                movie=rendered_media or (Path(dialog.movie.text()) if path.suffix.lower()=='.otio' else None)
                return path,movie
        finally:
            dialog.deleteLater()

    def accept(self):
        self.setDefaultSuffix(self.formats[self.selectedNameFilter()])
        selected=self.selectedFiles()
        if selected:
            path=Path(selected[0])
            if not path.is_dir():
                editor=self.findChild(QLineEdit,'fileNameEdit')
                if path.suffix.lower().lstrip('.') not in self.formats.values():
                    path=path.with_name(path.name+'.'+self.defaultSuffix())
                    editor.setText(str(path))
                if path.suffix.lower()=='.otio' and self.movie_row is not None:
                    self.movie_row.show()
                    if not Path(self.movie.text()).is_file() and not self.choose_movie():
                        return
        super().accept()


@dataclass(frozen=True)
class RenderedTimeline:
    state: State
    fps: Fraction


def offer_rendered_markers(window,media_path,state,fps):
    if not state.frame_markers:
        return
    answer=QMessageBox.question(window,tr('Marqueurs'),tr('Enregistrer aussi les marqueurs ?'),
                                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
    if answer!=QMessageBox.Yes:
        return
    media_path=Path(media_path).resolve()
    result=CommentExportDialog.destination(window,media_path)
    if result:
        path,movie=result
        rendered=RenderedTimeline(state,fps)
        try:
            if path.exists() and path.samefile(media_path):
                raise ValueError(tr('Choisissez un fichier différent du média exporté.'))
            if path.suffix.lower()=='.otio':
                if media_path.suffix.lower() in ('.png','.tga','.exr'):
                    write_otio(path,rendered,movie,image_sequence=True)
                else:
                    write_otio(path,rendered,movie)
            else:
                write_csv(path,rendered)
        except (OSError,ValueError,csv.Error) as error:
            window.error(tr('Le média a été exporté. L’enregistrement des marqueurs a échoué.')+'\n'+str(error))


class MarkerRows(QStyledItemDelegate):
    def row_text(self,option,index,width):
        metrics=option.fontMetrics
        span=index.data(DETAIL_ROLE) or ''
        title=index.data(TITLE_ROLE) or ''
        left=27
        content_width=max(0,width-left-5)
        span_width=min(metrics.horizontalAdvance(span),content_width//2 if title else content_width)
        title_left=left+span_width+9
        title_width=max(1,width-title_left-5)
        if not title:
            return span_width,title_left,[]
        layout=QTextLayout(title,option.font)
        wrap=QTextOption()
        wrap.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(wrap)
        layout.beginLayout()
        first=layout.createLine()
        first.setLineWidth(title_width)
        first_length=first.textLength()
        layout.endLayout()
        # QTextLine positions count UTF-16 units, including two units for emoji.
        encoded=title.encode('utf-16-le')
        split=2*first_length
        lines=[encoded[:split].decode('utf-16-le').rstrip()]
        if split<len(encoded):
            remainder=encoded[split:].decode('utf-16-le').lstrip()
            if remainder:
                lines.append(metrics.elidedText(remainder,Qt.ElideRight,title_width))
        return span_width,title_left,lines

    def sizeHint(self,option,index):
        _,_,lines=self.row_text(option,index,self.parent().viewport().width())
        return QSize(0,max(16,max(1,len(lines))*option.fontMetrics.lineSpacing())+6)

    def paint(self,painter,option,index):
        opt=QStyleOptionViewItem(option)
        self.initStyleOption(opt,index)
        symbol=QIcon(opt.icon)
        opt.text=''
        opt.icon=QIcon()
        opt.showDecorationSelected=True
        painter.save()
        painter.setClipRect(opt.rect)
        self.parent().style().drawControl(QStyle.CE_ItemViewItem,opt,painter,self.parent())
        painter.translate(opt.rect.topLeft())
        width,height=opt.rect.width(),opt.rect.height()
        symbol.paint(painter,QRect(5,(height-16)//2,16,16))
        selected=bool(opt.state & QStyle.State_Selected)
        painter.setPen(opt.palette.color(QPalette.HighlightedText if selected else QPalette.Text))
        painter.setFont(opt.font)
        span_width,title_left,lines=self.row_text(opt,index,width)
        align=Qt.AlignLeft|Qt.AlignVCenter
        span=opt.fontMetrics.elidedText(index.data(DETAIL_ROLE) or '',Qt.ElideRight,span_width)
        painter.drawText(QRect(27,0,span_width,height),align,span)
        line_height=opt.fontMetrics.lineSpacing()
        y=(height-len(lines)*line_height)//2
        for line in lines:
            painter.drawText(QRect(title_left,y,max(0,width-title_left-5),line_height),align,line)
            y+=line_height
        painter.restore()


class ReviewPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.host=window
        self.setObjectName('studioInspector')
        self.source=None
        self.edited=None
        self.shown=None
        self.frame=None
        self.document=ref(window.doc)
        self.draft=('',())
        self.following=None
        self.seen_selection=None
        self.timeline_ranges=()
        col=QVBoxLayout(self)
        col.setContentsMargins(9,8,9,8)
        self.splitter=LibrarySplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        col.addWidget(self.splitter)
        upper=QWidget()
        top=QVBoxLayout(upper)
        top.setContentsMargins(0,0,0,0)
        self.items=QListWidget()
        self.items.setMinimumSize(0,30)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items.setTextElideMode(Qt.ElideRight)
        self.items.setWordWrap(True)
        self.items.setResizeMode(QListView.Adjust)
        self.items.setItemDelegate(MarkerRows(self.items))
        self.items.currentItemChanged.connect(lambda item,_previous:self.seek_item(item))
        self.items.itemClicked.connect(self.seek_item)
        self.items.setContextMenuPolicy(Qt.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self.marker_menu)
        self.items.setAccessibleName(tr('Marqueurs'))
        top.addWidget(self.items,1)
        row=QHBoxLayout()
        self.add=style_button(QPushButton(tr('Marqueur')),'plus')
        self.add.setToolTip(tr('Ajouter un marqueur'))
        self.add.setAccessibleName(tr('Ajouter un marqueur'))
        self.add.clicked.connect(self.add_marker)
        row.addWidget(self.add,1)
        for text,symbol,slot in [('Importer les commentaires…','folder',self.import_file),
                                 ('Exporter les commentaires…','export',self.export_file)]:
            button=style_button(QPushButton(tr(text)),symbol,True)
            button.clicked.connect(slot)
            row.addWidget(button)
        top.addLayout(row)
        self.splitter.addWidget(upper)
        lower=QWidget()
        bottom=QVBoxLayout(lower)
        bottom.setContentsMargins(0,0,0,0)
        form=QHBoxLayout()
        self.duration=QSpinBox()
        self.duration.setRange(1,1)
        self.duration.setKeyboardTracking(False)
        self.duration.valueChanged.connect(self.store)
        self.ranges=QLineEdit()
        self.ranges.setMinimumWidth(0)
        self.ranges.setPlaceholderText('5, 8, 10–20')
        self.ranges.editingFinished.connect(self.apply_ranges)
        self.ranges.returnPressed.connect(self.confirm_draft_frame)
        self.ranges.textEdited.connect(self.clear_range_error)
        self.range_stack=QStackedWidget()
        self.range_stack.addWidget(self.duration)
        self.range_stack.addWidget(self.ranges)
        self.range_stack.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
        self.range_label=QLabel()
        for widget in (self.range_label,self.duration,self.ranges):
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda point,source=widget:self.range_menu(source,point))
        form.addWidget(self.range_label)
        form.addWidget(self.range_stack,1)
        bottom.addLayout(form)
        self.text=ReviewEditor()
        self.text.setPlaceholderText(tr('Commentaire'))
        self.text.setAccessibleName(tr('Commentaire'))
        self.text.setMinimumSize(0,32)
        self.text.installEventFilter(self)
        self.items.installEventFilter(self)
        self.items.viewport().installEventFilter(self)
        self.text.setStyleSheet('QTextEdit {background:#111820;border:1px solid #394654;border-radius:4px;padding:4px;}')
        self.text.textChanged.connect(self.store)
        bar=QHBoxLayout()
        bar.setSpacing(3)
        self.styles={}
        self.format_bar=QWidget()
        self.format_bar.setStyleSheet('QToolButton { padding:0; min-height:23px; }')
        self.format_bar.setLayout(bar)
        bar.setContentsMargins(0,0,0,0)
        for mask,label,symbol in ((BOLD,'Gras','B'),(ITALIC,'Italique','I'),(UNDERLINE,'Souligné','U'),
                                  (STRIKE,'Barré','S'),(0,'Case à cocher','')):
            button=QToolButton()
            button.setText(symbol)
            button.setToolTip(tr(label))
            button.setAccessibleName(tr(label))
            button.setFocusPolicy(Qt.NoFocus)
            button.setFixedSize(25,25)
            font=button.font()
            font.setBold(mask==BOLD)
            font.setItalic(mask==ITALIC)
            font.setUnderline(mask==UNDERLINE)
            font.setStrikeOut(mask==STRIKE)
            button.setFont(font)
            bar.addWidget(button)
            if mask:
                self.styles[mask]=button
                button.setCheckable(True)
                button.clicked.connect(lambda checked=False,style=mask:self.text.toggle_style(style))
            else:
                self.checkbox=button
                button.setCursor(Qt.PointingHandCursor)
                button.setIcon(icon('checkbox', color='#ffffff'))
                button.setIconSize(QSize(16,16))
                button.clicked.connect(self.text.add_box)
        bar.addStretch()
        bottom.addWidget(self.format_bar)
        bottom.addWidget(self.text,1)
        self.text.currentCharFormatChanged.connect(self.style_buttons)
        self.text.selectionChanged.connect(self.style_buttons)
        self.text.textChanged.connect(self.style_buttons)
        self.splitter.addWidget(lower)
        self.splitter.setSizes([250,240])
        saved=window.settings.value('review/comments_split')
        if isinstance(saved,QByteArray): self.splitter.restoreState(saved)
        self.splitter.splitterMoved.connect(lambda *_:window.settings.setValue('review/comments_split',self.splitter.saveState()))
        self.set_range_mode(window.settings.value('review/frame_ranges',False,type=bool))

    def style_buttons(self):
        mask=self.text.active_styles()
        for style,button in self.styles.items():
            button.setEnabled(mask is not None)
            button.setChecked(bool((mask or 0) & style))

    def seek_item(self,item):
        if item is not None and not self.host.job:
            frame=item.data(Qt.UserRole)
            self.following=None
            self.timeline_ranges=()
            if frame is not None and frame!=self.host.doc.state.position:
                self.host.pause()
                self.host.seek(frame)
            else:
                self.refresh()

    def remove_item(self,item):
        if item is None or self.host.job:
            return
        state=self.host.doc.state
        frame=item.data(Qt.UserRole)
        row=self.items.row(item)
        self.host.pause()
        remaining=tuple(f for f in state.frame_markers if f!=frame)
        if self.host.doc.commit('Supprimer le marqueur',replace(state,frame_markers=remaining)):
            self.timeline_ranges=()
            self.following=(state.position,frame,remaining[min(row,len(remaining)-1)]) if remaining else None
            self.host.refresh()

    def marker_menu(self,point):
        item=self.items.itemAt(point)
        if item is None: return
        with QSignalBlocker(self.items): self.items.setCurrentItem(item)
        menu=QMenu(self)
        remove=menu.addAction(tr('Supprimer le marqueur'))
        rename=menu.addAction(tr('Renommer le marqueur…'))
        action=menu.exec(self.items.viewport().mapToGlobal(point))
        if action==remove:
            self.remove_item(item)
        elif action==rename:
            self.host.drawing.rename_marker(item.data(Qt.UserRole))
        else:
            self.refresh()

    def set_range_mode(self,ranges):
        self.range_mode=ranges
        if not ranges: self.timeline_ranges=()
        self.host.settings.setValue('review/frame_ranges',ranges)
        self.update_range_field()
        if self.isVisible(): self.refresh()

    def update_range_field(self):
        ranges=bool(self.timeline_ranges) or self.range_mode
        widget=self.ranges if ranges or self.frame is None else self.duration
        label='Durée (images)' if self.frame is not None else 'Image'
        label=tr('Plages d’images' if ranges else label)
        if self.range_stack.currentWidget() is widget and self.range_label.text()==label: return
        self.range_stack.setCurrentWidget(widget)
        self.range_label.setText(label)
        self.range_label.setBuddy(widget)
        widget.setAccessibleName(label)

    def range_menu(self,widget,point):
        menu=QMenu(self)
        for index,label in enumerate(('Durée (images)' if self.frame is not None else 'Image','Plages d’images')):
            action=menu.addAction(tr(label))
            action.setCheckable(True)
            action.setChecked(index==int(bool(self.timeline_ranges) or self.range_mode))
            action.triggered.connect(lambda _,mode=index:self.set_range_mode(bool(mode)))
        menu.exec(widget.mapToGlobal(point))

    def clear_range_error(self):
        if self.ranges.accessibleDescription():
            self.ranges.setAccessibleDescription('')
            self.ranges.setToolTip('')
            self.ranges.setStyleSheet('')

    def confirm_draft_frame(self):
        if (self.timeline_ranges or self.frame is None and self.draft[0]) and not self.ranges.isModified():
            self.apply_ranges(force=True)

    def apply_ranges(self,force=False):
        if not (force or self.ranges.isModified()) or self.host.job:
            return
        self.clear_range_error()
        try:
            ranges=frame_ranges(self.ranges.text(),self.host.doc.state.length)
            changed=self.host.doc.set_marker_ranges(self.frame,ranges,draft=self.draft)
            self.ranges.setModified(False)
            if changed:
                if self.frame is None: self.draft=('',())
                self.timeline_ranges=()
                self.following=None
                self.host.pause()
                self.host.seek(next(iter(ranges)))
                self.host.refresh()
        except ValueError as error:
            message=tr(str(error))
            self.ranges.setStyleSheet('QLineEdit {border:1px solid #e59c71;}')
            self.ranges.setToolTip(message)
            self.ranges.setAccessibleDescription(message)
            QToolTip.showText(self.ranges.mapToGlobal(self.ranges.rect().bottomLeft()),message,self.ranges)
            return
        self.refresh()

    def eventFilter(self,watched,event):
        if watched is self.text and event.type()==QEvent.FocusOut:
            self.edited=None
        if event.type()==QEvent.MouseButtonPress and event.button()==Qt.RightButton and watched is self.items.viewport():
            item=self.items.itemAt(event.position().toPoint())
            if item is not None:
                with QSignalBlocker(self.items): self.items.setCurrentItem(item)
        if watched is self.items and event.type() in (QEvent.ShortcutOverride,QEvent.KeyPress):
            if event.modifiers()==Qt.NoModifier and event.key() in (Qt.Key_Delete,Qt.Key_Up,Qt.Key_Down):
                if event.type()==QEvent.ShortcutOverride:
                    event.accept()
                    return True
                if event.key()==Qt.Key_Delete:
                    self.remove_item(self.items.currentItem())
                    return True
        return super().eventFilter(watched,event)

    def showEvent(self,event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        if not self.isVisible(): return
        if self.document() is not self.host.doc:
            self.document=ref(self.host.doc)
            self.draft=('',())
            self.following=None
            self.seen_selection=None
            self.ranges.setModified(False)
            self.edited=None
        state=self.host.doc.state
        selection=(state.selection,state.selected_clips)
        if self.seen_selection!=selection:
            self.seen_selection=selection
            self.timeline_ranges=tuple(self.host.doc.marker_target_ranges().items()) if state.selection else ()
            self.following=None
            self.ranges.setModified(False)
            self.clear_range_error()
        key=(state.frame_markers,state.marker_names,state.marker_notes,state.marker_styles)
        with QSignalBlocker(self.items):
            if self.source is None or not all(a is b for a,b in zip(self.source,key)):
                self.source=key
                self.notes={f:(d,text) for f,d,text in state.marker_notes}
                self.formats=dict(state.marker_styles)
                self.times,self.owners=active_intervals(state.frame_markers,self.notes)
                names=dict(state.marker_names)
                for i,f in enumerate(state.frame_markers):
                    item=self.items.item(i)
                    if item is None:
                        item=QListWidgetItem(icon('mark'),'')
                        self.items.addItem(item)
                    duration,text=self.notes.get(f,(1,''))
                    label=names.get(f) or ' '.join(text.splitlines())
                    span=str(f) if duration==1 else f'{f}–{f+duration-1}'
                    item.setText(f'{span}   {label}' if label else span)
                    item.setData(Qt.UserRole,f)
                    item.setData(DETAIL_ROLE,span)
                    item.setData(TITLE_ROLE,label)
                while self.items.count()>len(state.frame_markers):
                    self.items.takeItem(self.items.count()-1)
            i=bisect_right(self.times,state.position)-1
            frame=self.owners[i] if i>=0 else None
            if self.timeline_ranges:
                start=self.timeline_ranges[0][0]
                frame=start if start in state.frame_markers else None
            if self.following is not None:
                position,deleted,following=self.following
                if position==state.position and deleted not in state.frame_markers and following in state.frame_markers:
                    frame=following
                else:
                    self.following=None
            target=bisect_right(state.frame_markers,frame)-1 if frame is not None else -1
            if self.items.currentRow()!=target: self.items.setCurrentRow(target)
        if self.frame!=frame:
            self.edited=None
            self.ranges.setModified(False)
            self.clear_range_error()
        self.frame=frame
        self.update_range_field()
        self.add.setEnabled(bool(state.selection or (0<=state.position<state.length and state.position not in state.frame_markers)))
        self.range_stack.setEnabled(state.length>0)
        duration,text=self.notes.get(frame,(1,''))
        with QSignalBlocker(self.duration):
            self.duration.setRange(1,max(1,state.length-frame) if frame is not None else 1)
            self.duration.setValue(duration)
        if not self.ranges.isModified():
            if self.timeline_ranges:
                span=', '.join(str(a) if d==1 else f'{a}-{a+d-1}' for a,d in self.timeline_ranges)
            elif frame is None:
                span=str(min(state.position,state.length-1)) if state.length else ''
            else:
                span=str(frame) if duration==1 else f'{frame}-{frame+duration-1}'
            if span!=self.ranges.text(): self.ranges.setText(span)
        content=self.draft if frame is None else (text,self.formats.get(frame,()))
        if content!=self.shown:
            self.shown=content
            with QSignalBlocker(self.text): self.text.load(*content)
            self.style_buttons()


    def add_marker(self):
        w=self.host
        if w.job or not w.doc.state.length: return
        w.pause()
        ranges=w.doc.marker_target_ranges()
        if self.frame is None and self.draft[0]:
            try:
                changed=w.doc.set_marker_ranges(None,ranges,draft=self.draft)
            except ValueError as error:
                w.notify(tr(str(error)))
                return
            if changed: self.draft=('',())
        else:
            changed=w.doc.add_timeline_marker()
        if changed:
            self.following=None
            w.seek(next(iter(ranges)))
            w.refresh()
        self.text.setFocus()

    def toggle_hover_checkbox(self,frame,old,new):
        w=self.host
        if w.job: return
        for start,duration,text in w.doc.state.marker_notes:
            if start==frame and text==old:
                styles=dict(w.doc.state.marker_styles).get(frame,())
                if w.doc.set_marker_note(frame,duration,new,styles):
                    self.edited=None
                    w.refresh()
                break

    def store(self):
        w=self.host
        doc=w.doc
        if w.job: return
        if self.text.hasFocus() and w.transport.running: w.pause()
        self.shown=(self.text.toPlainText(),self.text.style_runs())
        if self.frame is None:
            self.draft=self.shown
            return
        previous=doc.undo_stack[-1] if doc.undo_stack else None
        editing=self.sender() is self.text
        if not doc.set_marker_note(self.frame,self.duration.value(),*self.shown):
            return
        if editing and previous is self.edited and previous is not None:
            last=doc.undo_stack.pop()
            doc.undo_stack[-1]=(last[0],previous[1],last[2])
        self.edited=doc.undo_stack[-1] if editing else None
        w.refresh()

    def export_file(self):
        w=self.host
        if not w.doc.state.frame_markers:
            w.notify(tr('Aucun marqueur à exporter.'))
            return
        source=next(iter(w.doc.media.values()),{}).get('path','')
        folder=w.settings.value('review/comment_export_folder','',type=str)
        result=CommentExportDialog.destination(self,folder=folder,source_hint=source)
        if result:
            path,movie=result
            try:
                if movie:
                    write_otio(path,w.doc,movie)
                else:
                    write_csv(path,w.doc)
                w.settings.setValue('review/comment_export_folder',str(path.parent))
            except (OSError,ValueError,csv.Error) as error:
                w.error(str(error))

    def import_file(self):
        w=self.host
        if w.job or not w.doc.state.length:
            return
        filters=tr('Commentaires (*.csv *.otio)')+';;'+tr('Tous les fichiers (*)')
        path,_=QFileDialog.getOpenFileName(self,tr('Importer les commentaires…'),'',filters)
        if not path: return
        try:
            suffix=Path(path).suffix.lower()
            if suffix not in ('.csv','.otio'):
                # Earlier exports could be saved without an extension.
                with open(path,'rb') as stream:
                    if stream.read(256).removeprefix(b'\xef\xbb\xbf').lstrip().startswith(b'{'):
                        suffix='.otio'
            if suffix=='.otio':
                mapped=read_otio(path,w.doc.fps,w.doc.state.length)
                w.pause()
                if merge_rows(w.doc,mapped): w.refresh()
                return
            kind,rows=load_csv(path)
            options={}
            if kind=='syncsketch':
                items=sorted({row['Item Name'] for row in rows})
                if len(items)>1:
                    item,ok=QInputDialog.getItem(self,tr('Importer les commentaires…'),tr('Média'),items,editable=False)
                    if not ok: return
                    rows=[row for row in rows if row['Item Name']==item]
            if kind!='cadence':
                dialog=QDialog(self)
                dialog.setWindowTitle(tr('Importer les commentaires…'))
                form=QFormLayout(dialog)
                rate=QLineEdit(str(w.doc.fps))
                origin=QLineEdit('00:00:00:00' if kind=='xstudio' else '1')
                destination=QSpinBox()
                destination.setRange(0,w.doc.state.length-1)
                for label,widget in [('Cadence source',rate),('Première image source',origin),
                                     ('Début dans le montage',destination)]:
                    form.addRow(tr(label),widget)
                buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                form.addRow(buttons)
                if dialog.exec()!=QDialog.Accepted: return
                source_rate=source_fps(rate.text())
                options=dict(source_rate=source_rate,origin=origin.text(),destination=destination.value())
            mapped=map_rows(kind,rows,w.doc.fps,w.doc.state.length,**options)
            w.pause()
            if merge_rows(w.doc,mapped): w.refresh()
        except (OSError,ValueError,csv.Error) as error:
            w.error(str(error))
