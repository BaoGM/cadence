# SPDX-License-Identifier: GPL-3.0-only
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


PATHS = {
    'time-warp': 'M3.5 18.5L8 12.5H13.5L20.5 4.5 M6.5 11H9.5V14H6.5Z M12 11H15V14H12Z',
    'exposure': 'M3.5 8V16 M20.5 8V16 M4 12H20',
    'doc': 'M5 3.5H14L19 8.5V20.5H5Z M14 3.5V9H19',
    'film': 'M3.5 5H20.5V19H3.5Z M7.5 5V19 M16.5 5V19 M3.5 10H7.5 M3.5 14H7.5 M16.5 10H20.5 M16.5 14H20.5',
    'playback': 'M4 5H19 M4 10H13 M4 15H10 M15 13L21 17L15 21Z',
    'edit': 'M3 6H21V10H3Z M3 15H15V19H3Z M17.5 13V21',
    'library': 'M2.5 8.5H9L11.3 11H21V19.5H2.5Z M4.5 5H11L13.4 7.4H19.3',
    'refs': 'M3.5 4.5H16.5V7.2 M3.5 4.5V14H6 M7.5 8.5H21V19H7.5Z',
    'folder': 'M2.5 6H9.2L11.5 8.5H21.4V18.8H2.5Z',
    'opened': 'M3 16.7V5.7H9.2L11.2 8H18V10 M3.1 18.6L6.5 10.5H22L18.8 18.6Z',
    'list': 'M8.7 6H20.5 M8.7 12H20.5 M8.7 18H20.5 M3.5 6H4 M3.5 12H4 M3.5 18H4',
    'time': 'M20.5 12A8.5 8.5 0 1 1 3.5 12A8.5 8.5 0 1 1 20.5 12 M12 7V12L15 14',
    'dock': 'M3 5H21V19H3Z M9 5V19',
    'dock-right': 'M3 5H21V19H3Z M15 5V19',
    'help': 'M20 12A8 8 0 1 1 4 12A8 8 0 1 1 20 12 M9.8 9A2.3 2.3 0 1 1 13 11.2Q12 11.7 12 13.1 M12 16H12.1',
    'cursor': 'M5 3L20 13L12.7 14.2L9.5 21Z',
    'pen': 'M4 19.6L5.2 14.5L16.9 2.8L20.8 6.8L9.1 18.5Z M14.9 4.9L18.8 8.8',
    'erase': 'M3 14.4L13.4 4L21.2 11.8L12.5 20.5H9Z M7.4 10L15.2 17.8 M12.5 20.5H21',
    'undo': 'M8.5 4.5L3.5 9.5L8.5 14.5 M4 9.5H14A5.5 5.5 0 0 1 14 20H10',
    'ab': 'M3 5H21V19H3Z M12 5V19',
    'sync-3d': 'M3 9L9.5 5.3L16 9V16.5L9.5 20.2L3 16.5Z M3 9L9.5 12.7L16 9 M9.5 12.7V20.2 M14 3.6A8.6 8.6 0 0 1 21 11.8 M18.2 9.9L21 12.6L23 9.4',
    'fit': 'M4 9V4H9 M15 4H20V9 M20 15V20H15 M9 20H4V15',
    'zoom': 'M16 14L21 19 M16.5 10A6.5 6.5 0 1 1 3.5 10A6.5 6.5 0 1 1 16.5 10',
    'down': 'M6 9L12 15L18 9',
    'right': 'M9 6L15 12L9 18',
    'up': 'M6 15L12 9L18 15',
    'plus': 'M12 5V19 M5 12H19',
    'minus': 'M5 12H19',
    'mark': 'M6 21V4H18L15 8L18 12H6',
    'key': 'M12 3.5L20.5 12L12 20.5L3.5 12Z',
    'comment': 'M4 4.5H20V16H10L5.5 20V16H4Z M7.5 8.5H16.5 M7.5 12H13',
    'checkbox': 'M3.5 3.5H20.5V20.5H3.5Z M7 12L10.4 15.4L17 8.8',
    'grip': 'M8 6H8.2 M15 6H15.2 M8 12H8.2 M15 12H15.2 M8 18H8.2 M15 18H15.2',
    'first': 'M4 5V19 M17.5 5L10 12L17.5 19',
    'prev': 'M15.5 5L8 12L15.5 19',
    'next': 'M8.5 5L16 12L8.5 19',
    'last': 'M20 5V19 M6.5 5L14 12L6.5 19',
    'play': 'M7 4.3L19 12L7 19.7Z',
    'pause': 'M7 5H9.5V19H7Z M14.5 5H17V19H14.5Z',
    'loop': 'M18.3 8H6.8L3.5 11.3V15.7L6.8 19H17L20.4 15.7V13 M15 4.3L18.8 8L15 11.7',
    'once': 'M18.3 8H6.8L3.5 11.3V15.7L6.8 19H17L20.4 15.7V13 M15 4.3L18.8 8L15 11.7 M3.6 5.2L21.3 20.7',
    'sound': 'M3 10H7L12.5 5V19L7 14H3Z M15.5 9Q18.5 12 15.5 15 M18 6Q23 12 18 18',
    'mute': 'M3 10H7L12.5 5V19L7 14H3Z M16 9L21 14 M21 9L16 14',
    'wave': 'M3 10V14 M7 7V17 M11 4V20 M15 8V16 M19 10V14',
    'open': 'M4 6.5V18H17.5 M10 13.5L19 4.5 M13.5 4.5H19.5V10.5',
    'refresh': 'M19 9A7.6 7.6 0 0 0 5.4 7.8 M19.3 4.5V9.3H14.6 M4.8 15A7.6 7.6 0 0 0 18.2 17 M4.7 19.6V14.8H9.4',
    'wipe': 'M9 7L4 12L9 17 M15 7L20 12L15 17',
    'menu': 'M4.5 6H19.5 M4.5 12H19.5 M4.5 18H19.5',
    'settings': 'M3.5 7.5H7 M11.5 7.5H20.5 M3.5 16.5H13 M17.5 16.5H20.5 M7 5.5H11.5V9.5H7Z M13 14.5H17.5V18.5H13Z',
    'lasso': 'M9 16.7C5.4 16 3.2 13.8 3.2 10.7C3.2 6.7 7.1 4.1 12 4.1C17 4.1 20.8 6.8 20.8 10.6C20.8 14.7 16.8 17.2 11.7 17.2C8.1 17.2 7.4 14.5 9.4 13.8C12.4 12.9 14 18.4 11 20.4',
    'translate': 'M12 3.2V20.8 M3.2 12H20.8 M8.9 6.4L12 3.2L15.1 6.4 M17.6 8.9L20.8 12L17.6 15.1 M15.1 17.6L12 20.8L8.9 17.6 M6.4 15.1L3.2 12L6.4 8.9',
    'text': 'M4.4 7.8V4.8H19.6V7.8 M12 4.8V19.3 M8.4 19.3H15.6',
    'picker': 'M6.5 14.1L14.9 5.7L18.2 9L9.8 17.4L5.2 18.7Z M12.8 5.3L18.6 11.1 M16.6 7.3L19 4.9Q20 3.8 19 2.9Q18 2 17.1 3.1L14.9 5.6',
    'arrow': 'M4.8 19.2L18.8 5.2 M10.8 5.2H18.8V13.2',
    'rectangle': 'M4.3 5.5H19.7V18.5H4.3Z',
    'ellipse': 'M20.2 12A8.2 6.7 0 1 1 3.8 12A8.2 6.7 0 1 1 20.2 12Z',
    'resize': 'M8 5.4H16 M18.6 8V16 M16 18.6H8 M5.4 16V8 M3.8 3.8H7V7H3.8Z M17 3.8H20.2V7H17Z M17 17H20.2V20.2H17Z M3.8 17H7V20.2H3.8Z',
    'crop': 'M7 3V16Q7 17 8 17H21 M3 7H16Q17 7 17 8V21',
    'swap': 'M3.8 8.2H19.7 M16.3 4.8L19.7 8.2L16.3 11.6 M20.2 15.8H4.3 M7.7 12.4L4.3 15.8L7.7 19.2',
    'more': 'M5.5 12H5.7 M11.9 12H12.1 M18.3 12H18.5',
    'keyboard': 'M3.2 5.8H20.8V18.2H3.2Z M6.6 9.2H6.8 M10.5 9.2H10.7 M14.4 9.2H14.6 M17.4 9.2H17.6 M7 13.7H8 M10.7 13.7H17',
    'cache': 'M4.2 5.2H19.8V10.8H4.2Z M4.2 13.1H19.8V18.8H4.2Z M7.1 8H7.4 M7.1 16H7.4',
    'close': 'M6.3 6.3L17.7 17.7 M17.7 6.3L6.3 17.7',
    'sync': 'M4 8.4L9 3.6L14 8.4L9 13.2Z M10.2 15.5L15.2 10.7L20.2 15.5L15.2 20.3Z',
    'export': 'M12 14V3.5 M8.5 7L12 3.5L15.5 7 M4.5 13.3V19.8H19.5V13.3',
    'clear': 'M4.3 6.7H19.7 M8.7 6.6V4.2H15.3V6.6 M6.6 7.3L7.5 19.7H16.5L17.4 7.3',
    'capture': 'M3.5 6H16V18H3.5Z M16 10L20.5 7.5V16.5L16 14',
    'brush-size': 'M4 17L15 6 M13 18H20 M16.5 14.5V21.5',
    'color': 'M12 3.5C10.6 6.2 5.3 11.7 5.3 14.8A6.7 6.7 0 0 0 18.7 14.8C18.7 11.7 13.4 6.2 12 3.5Z',
}


@lru_cache(maxsize=512)
def renderer(name, color):
    fill = color if name in ('play', 'pause') else 'none'
    data = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{PATHS[name]}" '
            f'fill="{fill}" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return QSvgRenderer(QByteArray(data.encode('ascii')))


def paint_icon(painter, rect, name, color):
    renderer(name, QColor(color).name()).render(painter, QRectF(rect))


@lru_cache(maxsize=512)
def raster(name, color, width, height):
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer(name, color).render(painter)
    painter.end()
    return pixmap


class StudioIconEngine(QIconEngine):
    def __init__(self, name, color):
        super().__init__()
        self.name = name
        self.color = color

    def clone(self):
        return StudioIconEngine(self.name, self.color)

    def ink(self, mode, state):
        if mode == QIcon.Mode.Disabled:
            return '#708192'
        return self.color or ('#68e0cf' if state == QIcon.State.On else '#d6e0e9')

    def paint(self, painter, rect, mode, state):
        renderer(self.name, self.ink(mode, state)).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        return QPixmap(raster(self.name, self.ink(mode, state), size.width(), size.height()))

    def scaledPixmap(self, size, mode, state, scale):
        pixels = size * scale
        result = self.pixmap(pixels, mode, state)
        result.setDevicePixelRatio(scale)
        return result


@lru_cache(maxsize=256)
def icon(name, color=None, size=18):
    return QIcon(StudioIconEngine(name, QColor(color).name() if color else None))
