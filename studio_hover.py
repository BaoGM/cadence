# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QCursor, QPainter, QColor
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout
from shiboken6 import isValid


class ReaderHeader(QFrame):
    video_span = None

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.video_span is None: return
        left,right=self.video_span
        painter=QPainter(self)
        background=QColor('#141b22')
        painter.fillRect(0,0,left,self.height(),background)
        painter.fillRect(right,0,self.width()-right,self.height(),background)


def overlay(parent, frame_type=QFrame):
    flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus
    frame = frame_type(parent, flags)
    frame.setAttribute(Qt.WA_TranslucentBackground)
    frame.setAttribute(Qt.WA_ShowWithoutActivating)
    frame.setFocusPolicy(Qt.NoFocus)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0,0,0,0)
    layout.setSpacing(0)
    return frame


class HoverHeaders(QObject):
    def __init__(self, chrome):
        super().__init__(chrome.w)
        self.chrome = chrome
        self.w = chrome.w
        self.read = self.simple = False
        # Top-level translucent surfaces composite above the native OpenGL/Direct3D video windows.
        self.top = overlay(self.w,ReaderHeader)
        self.view = overlay(self.w)
        self.ruler = overlay(self.w)
        self.top.setStyleSheet('QFrame#studioTop {background:rgba(20,27,34,205);}')
        self.view.setStyleSheet('QFrame#studioView {background:rgba(20,27,34,205);}')
        self.ruler.setStyleSheet('QFrame#studioTimeline {background:rgba(22,29,37,210);}')
        self.timer = QTimer(self)
        self.timer.setInterval(65)
        self.timer.timeout.connect(self.update_hover)
        self.w.installEventFilter(self)
        self.w.timeline_panel.installEventFilter(self)

    def configure(self, read, simple):
        c = self.chrome
        if read != self.read:
            self.read = read
            for widget,host,home in ((c.top,self.top,c.top_slot),(c.view,self.view,self.w.viewer_workspace.content)):
                if read:
                    host.layout().addWidget(widget)
                else:
                    host.hide()
                    home.layout().insertWidget(0,widget)
                widget.show()
        c.bar.setVisible(not read and not self.w.video_fullscreen)
        if simple != self.simple:
            self.simple = simple
            bar = c.timeline_bar
            if simple:
                self.ruler.layout().addWidget(bar)
            else:
                self.ruler.hide()
                self.w.timeline_panel.widget().layout().insertWidget(0,bar)
            bar.show()
        pad = (0,0,0,0) if read or self.w.video_fullscreen else (4,4,4,4) if self.w.width()<=760 else (17,9,17,9)
        c.stage_layout.setContentsMargins(*pad)
        self.update_hover()

    def geometries(self):
        c,w = self.chrome,self.w
        area=w.viewer_workspace.content
        corner=area.mapToGlobal(QPoint(0,0))
        first=QRect(w.mapToGlobal(QPoint(0,0)).x(),corner.y(),w.width(),c.top.height())
        second=QRect(corner.x(),first.bottom()+1,area.width(),c.view.height())
        panel=w.timeline_panel.widget()
        pos=panel.mapToGlobal(QPoint(0,0))
        ruler=QRect(pos.x(),pos.y()-c.timeline_bar.height(),panel.width(),c.timeline_bar.height())
        transport=self.transport_rect()
        if (not w.timeline_panel.isFloating() and not w.transport_widget.isFloating()
                and w.dockWidgetArea(w.transport_widget)==Qt.BottomDockWidgetArea and ruler.intersects(transport)):
            ruler.moveBottom(transport.top()-1)
        return first,second,ruler

    def transport_rect(self):
        dock=self.w.transport_widget
        return QRect(dock.mapToGlobal(QPoint()),dock.size()) if dock.isVisible() else QRect()

    def show_reader(self):
        if not self.read or self.w.video_fullscreen: return
        first,second,_=self.geometries()
        span=second.x()-first.x(),second.right()-first.x()+1
        if self.top.video_span!=span:
            self.top.video_span=span
            self.top.update()
        for host,rect in ((self.top,first),(self.view,second)):
            if host.geometry()!=rect: host.setGeometry(rect)
            if not host.isVisible(): host.show(); host.raise_()

    def update_hover(self, point=None):
        w=self.w
        tracking=(self.read or self.simple) and w.isVisible() and not w.isMinimized() and not w.video_fullscreen
        if tracking and not self.timer.isActive(): self.timer.start()
        elif not tracking: self.timer.stop()
        if not tracking or QApplication.activeModalWidget():
            for frame in (self.top,self.view,self.ruler): frame.hide()
            return
        if point is None:
            # A floating strip appearing during a drag can take capture from the timeline.
            if QApplication.mouseButtons() or w.timeline.gesture or w.timeline.external_scrubbing:
                return
            active=QApplication.activeWindow()
            if not w.isActiveWindow() and active not in (w,self.top,self.view,self.ruler) and not QApplication.activePopupWidget():
                for frame in (self.top,self.view,self.ruler): frame.hide()
                return
            point=QCursor.pos()
        first,second,bar=self.geometries()
        popup=QApplication.activePopupWidget()
        def keep(host):
            grab=w.mouseGrabber()
            return (popup is not None and host.isAncestorOf(popup)) or (grab is not None and host.isAncestorOf(grab))
        if self.read and (first.contains(point) or second.adjusted(0,0,0,8).contains(point)
                or self.top.isVisible() and (keep(self.top) or keep(self.view))):
            self.show_reader()
        else:
            self.top.hide()
            self.view.hide()
        timeline=QRect(w.timeline.mapToGlobal(QPoint()),w.timeline.size())
        if self.simple and w.timeline_panel.isVisible() and (
                bar.adjusted(0,-12,0,12).contains(point) or timeline.adjusted(0,-12,0,4).contains(point)
                or self.transport_rect().contains(point) or self.ruler.isVisible() and keep(self.ruler)):
            if self.ruler.geometry()!=bar: self.ruler.setGeometry(bar)
            if not self.ruler.isVisible(): self.ruler.show(); self.ruler.raise_()
        else: self.ruler.hide()

    def eventFilter(self, obj, event):
        if isValid(self.w) and event.type() in (QEvent.Show,QEvent.Hide,QEvent.WindowStateChange,QEvent.Close):
            self.update_hover()
        return False
