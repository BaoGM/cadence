# SPDX-License-Identifier: GPL-3.0-only
from functools import lru_cache
from fractions import Fraction
from xml.sax.saxutils import quoteattr

from PySide6.QtCore import QByteArray, QRect, QSize, Qt, QSettings
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QTabBar, QStyledItemDelegate, QStyle

from ui_text import tr


PATHS = {
    'playback': 'M4 5H19 M4 10H13 M4 15H10 M15 13L21 17L15 21Z',
    'film': 'M3.5 5H20.5V19H3.5Z M7.5 5V19 M16.5 5V19 M3.5 10H7.5 M3.5 14H7.5 M16.5 10H20.5 M16.5 14H20.5',
    'library': 'M2.5 8.5H9L11.3 11H21V19.5H2.5Z M4.5 5H11L13.4 7.4H19.3',
    'refs': 'M3.5 4.5H16.5V7.2 M3.5 4.5V14H6 M7.5 8.5H21V19H7.5Z',
    'folder': 'M2.5 6H9.2L11.5 8.5H21.4V18.8H2.5Z',
    'opened': 'M3 16.7V5.7H9.2L11.2 8H18V10 M3.1 18.6L6.5 10.5H22L18.8 18.6Z',
    'list': 'M8.7 6H20.5 M8.7 12H20.5 M8.7 18H20.5 M3.5 6H4 M3.5 12H4 M3.5 18H4',
    'time': 'M20.5 12A8.5 8.5 0 1 1 3.5 12A8.5 8.5 0 1 1 20.5 12 M12 7V12L15 14',
    'plus': 'M12 5V19 M5 12H19', 'minus': 'M5 12H19',
    'refresh': 'M19 9A7.6 7.6 0 0 0 5.4 7.8 M19.3 4.5V9.3H14.6 M4.8 15A7.6 7.6 0 0 0 18.2 17 M4.7 19.6V14.8H9.4',
    'wave': 'M3 10V14 M7 7V17 M11 4V20 M15 8V16 M19 10V14',
    'up': 'M6 15L12 9L18 15', 'down': 'M6 9L12 15L18 9',
    'open': 'M4 6.5V18H17.5 M10 13.5L19 4.5 M13.5 4.5H19.5V10.5',
}


@lru_cache(maxsize=None)
def icon(name, active=False):
    color = '#68e0cf' if active else '#d3deea'
    path = quoteattr(PATHS[name])
    source = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d={path} fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    svg = QSvgRenderer(QByteArray(source.encode()))
    result = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        svg.render(painter)
        painter.end()
        result.addPixmap(pm)
    return result


class LibraryTabs(QTabBar):
    symbols = ('playback', 'film', 'library', 'refs')

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.compact = settings.value('library/compact_tabs', True, type=bool)
        self.currentChanged.connect(lambda i:self.setIconSize(QSize(18+i,18+i)))
        self.setDrawBase(False)
        self.setExpanding(True)
        font = self.font()
        font.setPixelSize(12)
        self.setFont(font)

    def tabSizeHint(self, index):
        width = self.fontMetrics().horizontalAdvance(self.tabText(index))
        if self.compact:
            return QSize(30 if index != self.currentIndex() else width + 34, 34)
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
        for i in range(self.count()):
            rect = self.tabRect(i)
            selected = i == self.currentIndex()
            painter.fillRect(rect, QColor('#203136' if selected else '#141a21'))
            name = self.tabText(i)
            if self.compact:
                w = self.fontMetrics().horizontalAdvance(name) + 5 if selected else 0
                left = rect.center().x() - (18 + w)//2
                picture = QRect(left, rect.center().y()-9, 18, 18)
                label = QRect(left+21, rect.y(), w, rect.height())
            else:
                picture = QRect(rect.center().x()-9, rect.y()+5, 18, 18)
                label = rect.adjusted(1, 23, -1, -3)
            icon(self.symbols[i], selected).paint(painter, picture)
            painter.setPen(QColor('#68e0cf' if selected else '#becbd9'))
            if selected or not self.compact:
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, name)
            if selected:
                painter.fillRect(rect.left()+4, rect.bottom()-1, rect.width()-8, 2, QColor('#68e0cf'))
            if self.hasFocus() and selected:
                painter.drawRect(rect.adjusted(1, 1, -2, -2))


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
    if icon_only:
        button.setText('')
        button.setFixedSize(32, 30)
    return button


GROUP_ROLE=int(Qt.ItemDataRole.UserRole)+1


class SourceRows(QStyledItemDelegate):
    def __init__(self,parent,ordered=False):
        super().__init__(parent)
        self.ordered=ordered

    def sizeHint(self,option,index):
        return QSize(100,48+(21 if index.data(GROUP_ROLE) else 0))

    def paint(self,painter,option,index):
        painter.save()
        rect=option.rect.adjusted(3,0,-3,-1)
        font=option.font
        group=index.data(GROUP_ROLE)
        if group:
            font.setPixelSize(11); painter.setFont(font); painter.setPen(QColor('#a3b3c3'))
            painter.drawText(rect.adjusted(5,0,-3,0),Qt.AlignTop|Qt.AlignLeft,group)
            rect.adjust(0,21,0,0)
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        if selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect,QColor('#203a3c' if selected else '#25313d'))
        if selected: painter.fillRect(rect.left(),rect.top(),2,rect.height(),QColor('#68e0cf'))
        text=index.data() or ''
        title,_,detail=text.partition('\n')
        x=rect.left()+7
        if self.ordered:
            rank,_,title=title.partition('. ')
            font.setPixelSize(12); painter.setFont(font); painter.setPen(QColor('#b5c6d6'))
            painter.drawText(QRect(x,rect.y(),20,rect.height()),Qt.AlignCenter,rank)
            x+=22
        iw=43 if self.ordered else 31
        tile=QRect(x,rect.center().y()-15,iw,30)
        painter.setPen(Qt.NoPen); painter.setBrush(QColor('#28494a' if selected else '#273440'))
        painter.drawRoundedRect(tile,4,4)
        picture=index.data(Qt.ItemDataRole.DecorationRole)
        if picture: picture.paint(painter,tile.adjusted(2,2,-2,-2))
        x+=iw+8
        room=max(0,rect.right()-x-(13 if self.ordered else 4))
        font.setPixelSize(13); painter.setFont(font); painter.setPen(QColor('#e4edf5'))
        label=painter.fontMetrics().elidedText(title,Qt.ElideMiddle,room)
        painter.drawText(QRect(x,rect.y()+(4 if detail else 0),room,20 if detail else rect.height()),Qt.AlignVCenter|Qt.AlignLeft,label)
        if detail:
            font.setPixelSize(11); painter.setFont(font); painter.setPen(QColor('#b1c0ce'))
            painter.drawText(QRect(x,rect.y()+24,room,17),Qt.AlignVCenter|Qt.AlignLeft,painter.fontMetrics().elidedText(detail,Qt.ElideRight,room))
        if self.ordered:
            painter.setPen(QColor('#8294a5'))
            for dy in (-4,0,4):
                for dx in (0,3): painter.drawPoint(rect.right()-7+dx,rect.center().y()+dy)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setBrush(Qt.NoBrush); painter.setPen(QColor('#618984')); painter.drawRoundedRect(rect.adjusted(0,0,-1,-1),3,3)
        painter.restore()
