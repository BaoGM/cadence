# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QRect, QTimer, Qt, QVariantAnimation
from PySide6.QtGui import QCursor, QRegion
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsOpacityEffect, QLayout, QVBoxLayout
from shiboken6 import isValid


class PanelSlide(QVariantAnimation):
    def __init__(self, widget, offset, window):
        super().__init__(widget)
        self.widget = widget
        self.container = widget.parentWidget()
        self.container.layout().activate()
        self.origin = widget.pos()
        self.original_mask = widget.mask()
        self.offset = offset
        self.window = window
        self.on_hidden = None
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
        on_hidden = self.on_hidden
        self.on_hidden = None
        widget.entrance = None
        self.stop()
        widget.removeEventFilter(self)
        self.container.removeEventFilter(self)
        widget.move(self.origin)
        if on_hidden is not None: on_hidden()
        if self.window is not None:
            self.window.setWindowOpacity(1.0)
        else:
            widget.setGraphicsEffect(None)
        if self.original_mask.isEmpty():
            widget.clearMask()
        else:
            widget.setMask(self.original_mask)
        self.container.layout().invalidate()
        self.container.layout().activate()
        self.deleteLater()

    def eventFilter(self, obj, event):
        if obj is self.widget and event.type() in (QEvent.Hide,QEvent.ParentAboutToChange):
            self.on_hidden = None
            self.finish()
        elif obj is self.container and event.type()==QEvent.Resize:
            self.finish()
        return False

    def play(self, on_hidden=None):
        self.on_hidden = on_hidden
        self.setDirection(QAbstractAnimation.Backward if on_hidden else QAbstractAnimation.Forward)
        if self.state() != QAbstractAnimation.Running:
            self.start()
        elif on_hidden is not None and self.currentTime()==0:
            self.finish()


def slide_in(widget, offset, window=None):
    if previous := getattr(widget, 'entrance', None):
        previous.play()
        return
    if widget.graphicsEffect() is not None: return
    entrance = PanelSlide(widget,offset,window)
    widget.entrance = entrance
    entrance.advance(0.0)
    entrance.play()


def slide_out(widget, offset, on_hidden, window=None):
    motion = getattr(widget, 'entrance', None)
    if motion is None:
        if widget.graphicsEffect() is not None:
            on_hidden()
            return
        motion = PanelSlide(widget,offset,window)
        widget.entrance = motion
    motion.play(on_hidden)


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
        self.read = self.auto_ruler = False
        # Top-level translucent surfaces composite above the native OpenGL/Direct3D video windows.
        self.top = overlay(self.w)
        self.ruler = overlay(self.w)
        self.top.setStyleSheet('QFrame#studioTop {background:rgba(20,27,34,205);}'
                               'QFrame#studioView {background:transparent;border:0;}'
                               '#studioTop QToolButton#studioMenuButton {padding:3px 4px;}')
        self.ruler.setStyleSheet('QFrame#studioTimeline {background:rgba(22,29,37,210);}')
        self.timer = QTimer(self)
        self.timer.setInterval(65)
        self.timer.timeout.connect(self.update_hover)
        self.top_space = 0
        self.ruler_docked = False
        self.reposition = QTimer(self)
        self.reposition.setSingleShot(True)
        self.reposition.timeout.connect(self.position_visible)
        self.pointer_surfaces=(self.w.timeline_panel,self.w.timeline_panel.widget(),self.w.timeline,
                               self.w.transport_widget,self.w.transport_widget.widget(),self.ruler)
        for widget in (self.w,self.w.viewer_workspace.content,*self.pointer_surfaces):
            widget.installEventFilter(self)

    def position_visible(self):
        for host, rect in zip((self.top,self.ruler),self.geometries()):
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
            elif motion:=getattr(bar,'entrance',None):
                motion.play()
        else:
            self.hide_docked_ruler()
            self.reveal(self.ruler,self.geometries()[1])

    def hide_docked_ruler(self):
        if self.ruler_docked:
            bar=self.chrome.timeline_bar
            self.ruler.layout().addWidget(bar)
            self.ruler_docked=False
            bar.show()
            self.w.sync_timeline_scroll()

    def conceal_ruler(self):
        if self.ruler_docked:
            slide_out(self.chrome.timeline_bar,QPoint(0,18),self.hide_docked_ruler)
        elif self.ruler.isVisible():
            slide_out(self.chrome.timeline_bar,QPoint(0,18),self.ruler.hide,self.ruler)

    def conceal_top(self):
        if self.top.isVisible():
            def hidden():
                self.top.hide()
                self.reserve_top(0)
            slide_out(self.chrome.top,QPoint(0,-18),hidden,self.top)

    def narrow_header(self):
        width=self.w.viewer_workspace.content.width()
        return width < 840 and width < self.w.width()-8

    def inline_ruler(self):
        w=self.w
        return (w.timeline_panel.isFloating() or w.dockWidgetArea(w.timeline_panel)!=Qt.BottomDockWidgetArea
                or w.viewer_workspace.content.width() < self.chrome.timeline_bar.minimumSizeHint().width())

    def configure(self, read, simple):
        c = self.chrome
        if read != self.read:
            self.read = read
            self.reserve_top(0)
            if read:
                self.top.layout().addWidget(c.top)
            else:
                self.top.hide()
                c.top_slot.layout().addWidget(c.top)
            c.combine_reader_header(read)
            c.top.show()
        c.bar.setVisible(not read and not self.w.video_fullscreen)
        auto_ruler=(read or simple) and not c.collapsed
        if auto_ruler != self.auto_ruler:
            self.auto_ruler = auto_ruler
            self.hide_docked_ruler()
            bar = c.timeline_bar
            if auto_ruler:
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
        panel=w.timeline_panel.widget()
        pos=panel.mapToGlobal(QPoint(0,0))
        ruler=QRect(pos.x(),pos.y()-c.timeline_bar.height(),panel.width(),c.timeline_bar.height())
        if self.inline_ruler():
            if self.ruler_docked:
                ruler.moveTop(pos.y())
            return first,ruler
        ruler.moveBottom(min(ruler.bottom(),corner.y()+area.height()-1))
        ruler.setLeft(corner.x())
        ruler.setWidth(area.width())
        return first,ruler

    def transport_rect(self):
        dock=self.w.transport_widget
        return QRect(dock.mapToGlobal(QPoint()),dock.size()) if dock.isVisible() else QRect()

    def lower_hover(self, point, bar):
        if bar.contains(point):
            return True
        transport=self.transport_rect()
        if transport.contains(point):
            return True
        # Include the dock separator only where it actually connects both strips.
        return (not transport.isEmpty() and 0 < transport.top()-bar.bottom() <= 8
                and bar.bottom()<point.y()<transport.top()
                and max(bar.left(),transport.left())<=point.x()<=min(bar.right(),transport.right()))

    def reveal(self, host, rect):
        if host.geometry()!=rect: host.setGeometry(rect)
        if not host.isVisible():
            host.setWindowOpacity(0)
            host.show()
            host.raise_()
            offset = QPoint(0,18 if host is self.ruler else -18)
            slide_in(host.layout().itemAt(0).widget(),offset,host)
            self.reposition.start(0)
        elif motion:=getattr(host.layout().itemAt(0).widget(),'entrance',None):
            motion.play()

    def show_reader(self):
        if not self.read or self.w.video_fullscreen: return
        if not self.chrome.side_motion.paths:
            self.reserve_top(self.chrome.top.height() if self.narrow_header() else 0)
        first,_=self.geometries()
        self.reveal(self.top,first)
        self.chrome.center_modes()

    def update_hover(self, point=None):
        w=self.w
        tracking=(self.read or self.auto_ruler) and w.isVisible() and not w.isMinimized() and not w.video_fullscreen
        if tracking and not self.timer.isActive(): self.timer.start()
        elif not tracking: self.timer.stop()
        if not tracking or QApplication.activeModalWidget():
            for frame in (self.top,self.ruler): frame.hide()
            self.reserve_top(0)
            self.hide_docked_ruler()
            return
        if QApplication.activePopupWidget(): return
        if point is None:
            # A floating strip appearing during a drag can take capture from the timeline.
            if QApplication.mouseButtons() or w.timeline.gesture or w.timeline.external_scrubbing:
                return
            active=QApplication.activeWindow()
            if not w.isActiveWindow() and active not in (self.top,self.ruler,w.timeline_panel,w.transport_widget):
                for frame in (self.top,self.ruler): frame.hide()
                self.reserve_top(0)
                self.hide_docked_ruler()
                return
            point=QCursor.pos()
        first,bar=self.geometries()
        def keep(host):
            grab=w.mouseGrabber()
            return grab is not None and host.isAncestorOf(grab)
        if self.top.isVisible():
            reader_hover=first.adjusted(0,0,0,8).contains(point) or keep(self.top)
        else:
            area=w.viewer_workspace.content
            approach=QRect(area.mapToGlobal(QPoint()),area.size())
            approach.setHeight(min(approach.height(),first.height()+8))
            reader_hover=approach.contains(point)
        if self.read and (reader_hover or self.top.isVisible() and self.chrome.side_motion.paths):
            self.show_reader()
        else:
            self.conceal_top()
        if self.auto_ruler and w.timeline_panel.isVisible() and (
                self.lower_hover(point,bar) or self.ruler.isVisible() and keep(self.ruler)):
            self.show_ruler()
        else:
            self.conceal_ruler()

    def eventFilter(self, obj, event):
        if not isValid(self.w): return False
        if obj in self.pointer_surfaces and self.auto_ruler:
            if event.type() in (QEvent.Enter,QEvent.MouseMove) and not QApplication.mouseButtons():
                if not self.w.timeline.gesture and not self.w.timeline.external_scrubbing:
                    self.update_hover(event.globalPosition().toPoint())
            elif event.type()==QEvent.Leave:
                self.update_hover()
        if event.type() in (QEvent.Move,QEvent.Resize,QEvent.LayoutRequest):
            if self.top.isVisible() or self.ruler.isVisible(): self.reposition.start(0)
        elif obj in (self.w,self.w.timeline_panel) and event.type() in (QEvent.Show,QEvent.Hide,QEvent.WindowStateChange,QEvent.Close):
            self.update_hover()
        return False
