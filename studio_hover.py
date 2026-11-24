# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRect, QTimer, Qt, QVariantAnimation
from PySide6.QtGui import QCursor, QRegion
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsOpacityEffect, QLayout, QVBoxLayout
from shiboken6 import isValid


class PanelEntrance(QVariantAnimation):
    def __init__(self, widget, offset, window):
        super().__init__(widget)
        self.widget = widget
        self.container = widget.parentWidget()
        self.container.layout().activate()
        self.origin = widget.pos()
        self.original_mask = widget.mask()
        self.offset = offset
        self.window = window
        self.effect = None
        if window is None:
            self.effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(self.effect)
        self.setDuration(180)
        self.setEasingCurve(QEasingCurve.OutCubic)
        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.valueChanged.connect(self.advance)
        self.finished.connect(self.finish)
        widget.installEventFilter(self)
        self.container.installEventFilter(self)

    def advance(self, progress):
        widget = self.widget
        shift = self.offset * (1.0 - progress)
        # Animate the actual controls inside their allocated space so hit testing follows them.
        clip = QRegion(widget.rect().intersected(widget.rect().translated(-shift)))
        if not self.original_mask.isEmpty():
            clip &= self.original_mask
        widget.setMask(clip)
        widget.move(self.origin + shift)
        if self.window is not None:
            self.window.setWindowOpacity(progress)
        else:
            self.effect.setOpacity(progress)

    def finish(self):
        widget = self.widget
        self.stop()
        widget.removeEventFilter(self)
        self.container.removeEventFilter(self)
        if self.window is not None:
            self.window.setWindowOpacity(1.0)
        else:
            widget.setGraphicsEffect(None)
        if self.original_mask.isEmpty():
            widget.clearMask()
        else:
            widget.setMask(self.original_mask)
        widget.move(self.origin)
        self.container.layout().invalidate()
        self.container.layout().activate()
        widget.entrance = None
        self.deleteLater()

    def eventFilter(self, obj, event):
        if (obj is self.widget and event.type() in (QEvent.Hide,QEvent.ParentAboutToChange)
                or obj is self.container and event.type()==QEvent.Resize):
            self.finish()
        return False


def slide_in(widget, offset, window=None):
    if previous := getattr(widget, 'entrance', None):
        previous.finish()
    if widget.graphicsEffect() is not None: return
    entrance = PanelEntrance(widget,offset,window)
    widget.entrance = entrance
    entrance.advance(0.0)
    entrance.start()


def overlay(parent):
    flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus
    frame = QFrame(parent, flags)
    frame.setAttribute(Qt.WA_TranslucentBackground)
    frame.setAttribute(Qt.WA_ShowWithoutActivating)
    frame.setFocusPolicy(Qt.NoFocus)
    layout = QVBoxLayout(frame)
    layout.setSizeConstraint(QLayout.SetNoConstraint)
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
        self.top = overlay(self.w)
        self.view = overlay(self.w)
        self.ruler = overlay(self.w)
        self.top.setStyleSheet('QFrame#studioTop {background:rgba(20,27,34,205);}')
        self.view.setStyleSheet('QFrame#studioView {background:rgba(20,27,34,205);}')
        self.ruler.setStyleSheet('QFrame#studioTimeline {background:rgba(22,29,37,210);}')
        self.timer = QTimer(self)
        self.timer.setInterval(65)
        self.timer.timeout.connect(self.update_hover)
        self.top_space = 0
        self.ruler_docked = False
        self.reposition = QTimer(self)
        self.reposition.setSingleShot(True)
        self.reposition.timeout.connect(self.position_visible)
        for widget in (self.w,self.w.viewer_workspace.content,self.w.timeline_panel,self.w.timeline_panel.widget()):
            widget.installEventFilter(self)

    def position_visible(self):
        for host, rect in zip((self.top,self.view,self.ruler),self.geometries()):
            if host.isVisible() and host.geometry()!=rect:
                host.setGeometry(rect)
        if self.top.isVisible():
            self.chrome.center_modes()

    def reserve_top(self, height):
        if self.top_space != height:
            self.top_space = height
            self.w.setContentsMargins(0, height, 0, 0)
            self.w.layout().activate()

    def show_ruler(self):
        bar=self.chrome.timeline_bar
        if self.inline_ruler():
            if not self.ruler_docked:
                self.ruler.hide()
                self.w.timeline_panel.widget().layout().insertWidget(0,bar)
                self.ruler_docked=True
                bar.show()
                self.w.sync_timeline_scroll()
                slide_in(bar,QPoint(0,18))
        else:
            self.hide_docked_ruler()
            self.reveal(self.ruler,self.geometries()[2])

    def hide_docked_ruler(self):
        if self.ruler_docked:
            bar=self.chrome.timeline_bar
            self.ruler.layout().addWidget(bar)
            self.ruler_docked=False
            bar.show()
            self.w.sync_timeline_scroll()

    def narrow_header(self):
        width=self.w.viewer_workspace.content.width()
        return width < 720 and width < self.w.width()-8

    def inline_ruler(self):
        w=self.w
        return (w.timeline_panel.isFloating() or w.dockWidgetArea(w.timeline_panel)!=Qt.BottomDockWidgetArea
                or w.viewer_workspace.content.width() < self.chrome.timeline_bar.minimumSizeHint().width())

    def configure(self, read, simple):
        c = self.chrome
        if read != self.read:
            self.read = read
            self.reserve_top(0)
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
            self.hide_docked_ruler()
            bar = c.timeline_bar
            if simple:
                self.ruler.layout().addWidget(bar)
            else:
                self.ruler.hide()
                self.w.timeline_panel.widget().layout().insertWidget(0,bar)
            bar.show()
        c.stage_layout.setContentsMargins(*c.stage_padding(read))
        self.update_hover()

    def geometries(self):
        c,w = self.chrome,self.w
        area=w.viewer_workspace.content
        corner=area.mapToGlobal(QPoint(0,0))
        first=QRect(corner.x(),corner.y(),area.width(),c.top.height())
        if self.narrow_header():
            first=QRect(w.mapToGlobal(QPoint()),w.size())
            first.setHeight(c.top.height())
        second=QRect(corner.x(),first.bottom()+1,area.width(),c.view.height())
        if area.width() < c.view.minimumSizeHint().width():
            second.setX(first.x())
            second.setWidth(first.width())
        elif self.narrow_header():
            second.moveTop(max(second.top(),corner.y()))
        panel=w.timeline_panel.widget()
        pos=panel.mapToGlobal(QPoint(0,0))
        ruler=QRect(pos.x(),pos.y()-c.timeline_bar.height(),panel.width(),c.timeline_bar.height())
        if self.inline_ruler():
            ruler.moveTop(pos.y())
            return first,second,ruler
        ruler.moveBottom(min(ruler.bottom(),corner.y()+area.height()-1))
        ruler.setLeft(corner.x())
        ruler.setWidth(area.width())
        return first,second,ruler

    def transport_rect(self):
        dock=self.w.transport_widget
        return QRect(dock.mapToGlobal(QPoint()),dock.size()) if dock.isVisible() else QRect()

    def reveal(self, host, rect):
        if host.geometry()!=rect: host.setGeometry(rect)
        if not host.isVisible():
            host.setWindowOpacity(0)
            host.show()
            host.raise_()
            offset = QPoint(0,18 if host is self.ruler else -18)
            slide_in(host.layout().itemAt(0).widget(),offset,host)
            self.reposition.start(0)

    def show_reader(self):
        if not self.read or self.w.video_fullscreen: return
        reserve=self.chrome.top.height() if self.narrow_header() else 0
        if self.w.viewer_workspace.content.width() < self.chrome.view.minimumSizeHint().width():
            reserve+=self.chrome.view.height()
        self.reserve_top(reserve)
        first,second,_=self.geometries()
        for host,rect in ((self.top,first),(self.view,second)):
            self.reveal(host,rect)
        self.chrome.center_modes()

    def update_hover(self, point=None):
        w=self.w
        tracking=(self.read or self.simple) and w.isVisible() and not w.isMinimized() and not w.video_fullscreen
        if tracking and not self.timer.isActive(): self.timer.start()
        elif not tracking: self.timer.stop()
        if not tracking or QApplication.activeModalWidget():
            for frame in (self.top,self.view,self.ruler): frame.hide()
            self.reserve_top(0)
            self.hide_docked_ruler()
            return
        if QApplication.activePopupWidget(): return
        if point is None:
            # A floating strip appearing during a drag can take capture from the timeline.
            if QApplication.mouseButtons() or w.timeline.gesture or w.timeline.external_scrubbing:
                return
            active=QApplication.activeWindow()
            if not w.isActiveWindow() and active not in (w,self.top,self.view,self.ruler) and not QApplication.activePopupWidget():
                for frame in (self.top,self.view,self.ruler): frame.hide()
                self.reserve_top(0)
                self.hide_docked_ruler()
                return
            point=QCursor.pos()
        first,second,bar=self.geometries()
        def keep(host):
            grab=w.mouseGrabber()
            return grab is not None and host.isAncestorOf(grab)
        if self.top.isVisible():
            reader_hover=first.contains(point) or second.adjusted(0,0,0,8).contains(point) or keep(self.top) or keep(self.view)
        else:
            area=w.viewer_workspace.content
            approach=QRect(area.mapToGlobal(QPoint()),area.size())
            approach.setHeight(min(approach.height(),first.height()+second.height()+8))
            reader_hover=approach.contains(point)
        if self.read and reader_hover:
            self.show_reader()
        else:
            self.top.hide()
            self.view.hide()
            self.reserve_top(0)
        timeline=QRect(w.timeline.mapToGlobal(QPoint()),w.timeline.size())
        if self.simple and w.timeline_panel.isVisible() and (
                bar.adjusted(0,-12,0,12).contains(point) or timeline.adjusted(0,-12,0,4).contains(point)
                or self.transport_rect().contains(point) or self.ruler.isVisible() and keep(self.ruler)):
            self.show_ruler()
        else:
            self.ruler.hide()
            self.hide_docked_ruler()

    def eventFilter(self, obj, event):
        if not isValid(self.w): return False
        if event.type() in (QEvent.Move,QEvent.Resize,QEvent.LayoutRequest):
            if self.top.isVisible() or self.ruler.isVisible(): self.reposition.start(0)
        elif obj in (self.w,self.w.timeline_panel) and event.type() in (QEvent.Show,QEvent.Hide,QEvent.WindowStateChange,QEvent.Close):
            self.update_hover()
        return False
