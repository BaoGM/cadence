# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QSizePolicy, QSplitter, QSplitterHandle,
                               QStyle, QStyledItemDelegate, QTabBar, QTabWidget, QTreeWidget, QWidget)

import studio_icons
from ui_text import tr


def icon(name, active=False, color=None):
    return studio_icons.icon(name, color=color or ('#68e0cf' if active else '#cbd7e2'))


PANEL_STYLE = """
QTabWidget::pane { border:0; background:#171e26; }
QTabWidget::tab-bar { left:0; }
QTabBar { background:#141b22; border:0; }
QWidget#studioPage,QWidget#studioPage QWidget { background-color:#171e26; }
QWidget#studioSection { border-bottom:1px solid #2a3440; }
QWidget#studioFooter { border-top:1px solid #333f4c; }
QLabel#studioHeading { font-size:13px; font-weight:600; color:#e3ecf6; background:transparent; }
QLabel#studioCount { font-size:11px; color:#9aaabb; background:transparent; }
QWidget#studioPage QListWidget,QWidget#studioPage QTreeWidget { border:0; padding:3px 7px; outline:0; }
QWidget#studioPage QTreeWidget { padding:5px 7px; selection-background-color:transparent; }
QWidget#studioPage QListWidget::item,QWidget#studioPage QTreeWidget::item { border:0; padding:0; }
QWidget#studioPage QPushButton { border:1px solid #394654; background:#232d38; color:#dce6ee; border-radius:4px; padding:2px 8px; min-height:21px; }
QWidget#studioPage QPushButton:hover { background:#2c3845; border-color:#627686; }
QWidget#studioPage QPushButton:checked { background:#203c3e; border-color:#548d85; color:#68e0cf; }
QWidget#studioPage QPushButton:disabled { color:#778695; background:#1b222b; border-color:#303b46; }
QWidget#studioPage QPushButton[flat="true"] { border:0; background:transparent; padding:0; }
QWidget#studioPage QPushButton[flat="true"]:hover { background:#26333d; }
QWidget#studioPage QComboBox { background:#111820; border:1px solid #394654; border-radius:4px; padding:3px 6px; }
QWidget#studioPage QComboBox QAbstractItemView { background:#1d2630; selection-background-color:#244044; }
"""


def panel_strip(layout, kind='section'):
    bar = QWidget()
    bar.setObjectName({'section':'studioSection','heading':'studioSubhead','footer':'studioFooter'}[kind])
    row = QHBoxLayout(bar)
    row.setContentsMargins(13 if kind=='heading' else 10, 6, 10, 4 if kind=='heading' else 6)
    row.setSpacing(5)
    if kind != 'heading':
        bar.setMinimumHeight(42 if kind=='footer' else 45)
    layout.addWidget(bar)
    return row


INSPECTOR_STYLE = """
QWidget#studioInspector,QWidget#studioInspector QWidget { background-color:#171e26; }
QWidget#studioInspector QLabel { color:#cdd8e2; background:transparent; }
QWidget#studioInspector QLabel#inspectorTitle { background:transparent; color:#e4ecf5; font-weight:600; font-size:13px; }
QWidget#studioInspector QCheckBox { spacing:7px; }
QWidget#studioInspector QComboBox,QWidget#studioInspector QLineEdit,QWidget#studioInspector QAbstractSpinBox {
 background:#111820; border:1px solid #394654; border-radius:4px; padding:4px 6px; min-height:16px; }
QWidget#studioInspector QAbstractSpinBox QLineEdit { border:0; padding:0; }
QWidget#studioInspector QComboBox QAbstractItemView { background:#1d2630; selection-background-color:#244044; }
QWidget#studioInspector QListWidget { border:1px solid #333f4c; border-radius:4px; background:#111820; padding:3px; }
QWidget#studioInspector QListWidget::item { padding:4px; }
QWidget#studioInspector QListWidget::item:selected { background:#244044; color:#e1edf1; }
QWidget#studioInspector QPushButton,QWidget#studioInspector QToolButton { border:1px solid #394654; background:#232d38; color:#dce6ee; border-radius:4px; padding:3px 6px; min-height:18px; }
QWidget#studioInspector QPushButton:hover,QWidget#studioInspector QToolButton:hover { background:#293540; border-color:#667b88; }
QWidget#studioInspector QToolButton:checked { color:#68e0cf; border-color:#487c78; background:#203b3e; }
QWidget#studioInspector QTabWidget::pane { background:#171e26; border:0; border-top:1px solid #333f4c; }
QWidget#studioInspector QTabBar::tab { border:0; background:#141b22; color:#a5b6c6; padding:5px 10px; }
QWidget#studioInspector QTabBar::tab:selected { background:#203036; color:#68e0cf; border-bottom:2px solid #68e0cf; }
"""


def inspector_heading(layout,text,symbol):
    line=QHBoxLayout(); line.setContentsMargins(0,5,0,2); line.setSpacing(7)
    picture=QLabel(); picture.setPixmap(icon(symbol,color='#9aaabb').pixmap(16,16))
    picture.setFixedSize(16,16); line.addWidget(picture)
    title=QLabel(tr(text)); title.setObjectName('inspectorTitle'); line.addWidget(title); line.addStretch()
    layout.addLayout(line)


class ElideLabel(QLabel):
    def __init__(self, text=''):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.contentsRect(), Qt.AlignLeft|Qt.AlignVCenter,
                         self.fontMetrics().elidedText(self.text(),Qt.ElideRight,self.contentsRect().width()))


def panel_heading(row, title):
    label=ElideLabel(title); label.setObjectName('studioHeading')
    row.addWidget(label,1)
    count=QLabel(); count.setObjectName('studioCount'); row.addWidget(count)
    return label,count


class LibraryPages(QTabWidget):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.tabBar().resize(self.contentsRect().width(),self.tabBar().sizeHint().height())

    def setCurrentWidget(self, widget):
        page=widget
        while page is not None and self.indexOf(page)<0 and page is not self:
            page=page.parentWidget()
        super().setCurrentWidget(page if page is not None and page is not self else widget)


class GripHandle(QSplitterHandle):
    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#111820'))
        painter.setPen(QColor('#333f4c')); painter.drawLine(0,0,self.width(),0)
        painter.drawLine(0,self.height()-1,self.width(),self.height()-1)
        painter.fillRect((self.width()-24)//2,(self.height()-2)//2,24,2,QColor('#687886'))


class LibrarySplitter(QSplitter):
    def createHandle(self):
        return GripHandle(self.orientation(),self)


class LibraryTabs(QTabBar):
    symbols = ('playback', 'film', 'library', 'refs')

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.compact = settings.value('library/compact_tabs', True, type=bool)
        self.currentChanged.connect(lambda i:self.setIconSize(QSize(18+i,18+i)))
        self.setDrawBase(False)
        self.setUsesScrollButtons(True)
        self.setExpanding(True)
        font = self.font()
        font.setPixelSize(12)
        self.setFont(font)

    def sizeHint(self):
        hint=super().sizeHint()
        parent=self.parentWidget()
        if parent is not None:
            hint.setWidth(max(hint.width(),parent.contentsRect().width()))
        return hint

    def minimumSizeHint(self):
        return QSize(150,self.sizeHint().height())

    def tabSizeHint(self, index):
        width = self.fontMetrics().horizontalAdvance(self.tabText(index))
        if self.compact:
            return QSize(34 if index != self.currentIndex() else width + 34, 42)
        return QSize(width + 11, 47)

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        action = menu.addAction(tr('Onglets compacts'))
        action.setCheckable(True)
        action.setChecked(self.compact)
        if menu.exec(event.globalPos()) is action:
            self.compact = action.isChecked()
            self.settings.setValue('library/compact_tabs', self.compact)
            self.setIconSize(QSize(18, 18) if self.compact else QSize(19, 19))
            self.updateGeometry()
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor('#141b22'))
        painter.fillRect(0,self.height()-1,self.width(),1,QColor('#333f4c'))
        for i in range(self.count()):
            rect = self.tabRect(i)
            selected = i == self.currentIndex()
            rect=rect.adjusted(1,4,-1,-1)
            if selected:
                painter.setPen(Qt.NoPen); painter.setBrush(QColor('#203036'))
                painter.drawRoundedRect(rect,4,4)
                painter.fillRect(rect.adjusted(0,rect.height()//2,0,0),QColor('#203036'))
            name = self.tabText(i)
            if self.compact:
                w = self.fontMetrics().horizontalAdvance(name) + 5 if selected else 0
                left = rect.center().x() - (18 + w)//2
                picture = QRect(left, rect.center().y()-9, 18, 18)
                label = QRect(left+21, rect.y(), w, rect.height())
            else:
                picture = QRect(rect.center().x()-9, rect.y()+5, 18, 18)
                label = rect.adjusted(1, 23, -1, -3)
            icon(self.symbols[i], selected, None if selected else '#9aaabb').paint(painter, picture)
            painter.setPen(QColor('#68e0cf' if selected else '#9aaabb'))
            if selected or not self.compact:
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, name)
            if selected:
                painter.fillRect(rect.left()+6, rect.bottom()-1, rect.width()-12, 2, QColor('#68e0cf'))
            if self.hasFocus() and selected:
                painter.setBrush(Qt.NoBrush); painter.drawRoundedRect(rect.adjusted(1,1,-2,-2),3,3)


def media_details(media):
    parts = []
    if media.get('has_video', True) and media.get('width') and media.get('height'):
        parts.append(f"{media['width']} × {media['height']}")
    fps = Fraction(str(media.get('fps') or 0))
    if fps and media.get('has_video', True):
        parts.append(f'{float(fps):g} '+tr('i/s'))
    if media.get('frames') and fps:
        seconds = int(media['frames'] / fps)
        parts.append(f'{seconds//60}:{seconds%60:02}')
    return ' · '.join(parts)


def style_button(button, symbol, icon_only=False):
    button.setIcon(icon(symbol))
    button.setAccessibleName(button.text())
    button.setToolTip(button.text())
    button.setIconSize(QSize(16,16))
    if icon_only:
        button.setText('')
        button.setFlat(True)
        button.setFixedSize(28,27)
    return button


TITLE_ROLE=int(Qt.ItemDataRole.UserRole)+1
DETAIL_ROLE=TITLE_ROLE+1
SYMBOL_ROLE=TITLE_ROLE+2
POSTER_ROLE=TITLE_ROLE+3
MEDIA_ROLE=TITLE_ROLE+4
PREVIEW_ROLE=TITLE_ROLE+5


def set_preview(item,media,frame=0):
    path=media.get('proxy') or media.get('path')
    if path and media.get('has_video',True):
        key=(path,media.get('size'),media.get('mtime_ns'),media.get('preview_rotation',0),
             frame,frame+1,str(media.get('fps') or 24),str(media.get('direct_start') or 0))
        item.setData(PREVIEW_ROLE,key)


def row_background(painter,rect,state):
    selected=bool(state & QStyle.StateFlag.State_Selected)
    if selected or state & QStyle.StateFlag.State_MouseOver:
        shape=QPainterPath()
        shape.addRoundedRect(QRectF(rect),5,5)
        painter.fillPath(shape,QColor('#244044' if selected else '#202c37'))
        if selected:
            painter.fillPath(shape.subtracted(shape.translated(2,0)),QColor('#68e0cf'))
    return selected


class LibraryTree(QTreeWidget):
    def drawRow(self,painter,option,index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRect(0,option.rect.y(),self.viewport().width(),option.rect.height())
        state=option.state
        if self.selectionModel().isSelected(index): state|=QStyle.StateFlag.State_Selected
        row_background(painter,rect,state)
        painter.restore()
        super().drawRow(painter,option,index)

    def drawBranches(self,painter,rect,index):
        if not self.model().hasChildren(index): return
        symbol='down' if self.isExpanded(index) else 'right'
        icon(symbol,color='#9aaabb').paint(painter,QRect(rect.right()-10,rect.center().y()-5,10,10))


class TreeRows(QStyledItemDelegate):
    row_height = 25

    def sizeHint(self,option,index):
        return QSize(64,self.row_height)

    def paint(self,painter,option,index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=option.rect.adjusted(0,0,0,-1)
        group=not index.parent().isValid()
        selected=self.parent().selectionModel().isSelected(index)
        symbol=index.data(SYMBOL_ROLE)
        if symbol:
            icon(symbol,selected,color=None if selected or not group else '#9aaabb').paint(
                painter,QRect(rect.left()+3,rect.center().y()-8,16,16))
        font=QFont(option.font); font.setPixelSize(12)
        painter.setFont(font); painter.setPen(QColor('#e0fbf4' if selected else '#9aaabb' if group else '#e1e8f0'))
        text_rect=rect.adjusted(24,0,-5,0)
        if group:
            count=str(index.model().rowCount(index))
            painter.drawText(text_rect,Qt.AlignRight|Qt.AlignVCenter,count)
            text_rect.adjust(0,0,-painter.fontMetrics().horizontalAdvance(count)-5,0)
        painter.drawText(text_rect,Qt.AlignLeft|Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(index.data() or '',Qt.ElideRight,text_rect.width()))
        painter.restore()


class EmptyHint(QLabel):
    def __init__(self,listing,text):
        from PySide6.QtCore import QEvent
        super().__init__(text,listing.viewport())
        self.resize_event=QEvent.Type.Resize
        self.setWordWrap(True); self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName('studioCount'); self.setMargin(12)
        listing.viewport().installEventFilter(self)
        listing.model().rowsInserted.connect(self.refresh)
        listing.model().rowsRemoved.connect(self.refresh)
        listing.model().modelReset.connect(self.refresh)
        self.listing=listing; self.refresh()

    def refresh(self,*args):
        self.setVisible(self.listing.count()==0 and bool(self.text()))

    def eventFilter(self,obj,event):
        if event.type()==self.resize_event: self.setGeometry(obj.rect())
        return False


class SourceRows(QStyledItemDelegate):
    row_height = 34

    def __init__(self,parent,ordered=False,thumbnails=None):
        super().__init__(parent)
        self.ordered=ordered
        self.thumbnails=thumbnails
        if thumbnails:
            thumbnails.changed.connect(parent.viewport().update)
        parent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        parent.setMouseTracking(True)

    def sizeHint(self,option,index):
        details = index.data(DETAIL_ROLE) or '\n' in (index.data() or '')
        return QSize(50,self.row_height + (4 if details else 0))

    def paint(self,painter,option,index):
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=option.rect
        font=QFont(option.font)
        active=row_background(painter,rect,option.state)
        text,_,secondary=(index.data() or '').partition('\n')
        title=index.data(TITLE_ROLE) or text
        detail=index.data(DETAIL_ROLE) or secondary
        left=rect.left()+7
        key=index.data(PREVIEW_ROLE)
        if self.ordered or key:
            poster=QRect(left,rect.center().y()-13,44,27)
            painter.setPen(Qt.NoPen); painter.setBrush(QColor('#10171d')); painter.drawRoundedRect(poster,3,3)
            if index.data(POSTER_ROLE):
                index.data(Qt.ItemDataRole.DecorationRole).paint(painter,poster)
            else:
                images=self.thumbnails.request((*key[:6],Fraction(key[6]),Fraction(key[7]))) if key and self.thumbnails else ()
                if images:
                    image=images[0]; scale=min(poster.width()/image.width(),poster.height()/image.height())
                    box=QRect(0,0,max(1,round(image.width()*scale)),max(1,round(image.height()*scale)))
                    box.moveCenter(poster.center()); painter.setRenderHint(QPainter.SmoothPixmapTransform)
                    painter.drawImage(box,image)
                else:
                    icon(index.data(SYMBOL_ROLE) or 'film',active).paint(painter,QRect(poster.center().x()-8,poster.center().y()-8,16,16))
            left+=52
        else:
            icon(index.data(SYMBOL_ROLE) or 'film',active).paint(painter,QRect(left,rect.center().y()-8,16,16))
            left+=24
        room=max(0,rect.right()-left-6)
        font.setPixelSize(13); painter.setFont(font); painter.setPen(QColor('#e0fbf4' if active else '#e1e8f0'))
        anchor=Qt.AlignLeft|Qt.AlignVCenter
        label=QRect(left,rect.top()+1 if detail else rect.top(),room,19 if detail else rect.height())
        painter.drawText(label,anchor,painter.fontMetrics().elidedText(title,Qt.ElideMiddle,room))
        if detail:
            font.setPixelSize(11); painter.setFont(font); painter.setPen(QColor('#9aaabb'))
            painter.drawText(QRect(left,rect.top()+19,room,15),anchor,
                             painter.fontMetrics().elidedText(detail,Qt.ElideRight,room))
        painter.restore()
