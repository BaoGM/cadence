# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject, QEvent, QRect, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QCheckBox
from shiboken6 import isValid


class HoverTransport(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.dock = window.transport_widget
        self.strip = self.dock.widget()
        self.overlay = QWidget(window)
        self.overlay.setObjectName('hover_transport')
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.overlay.setStyleSheet('#hover_transport {background:rgba(16,21,28,160);border:1px solid rgba(136,149,167,100);border-radius:5px;} QCheckBox {background:transparent;}')
        layout = QHBoxLayout(self.overlay); layout.setContentsMargins(9, 5, 9, 5)
        self.toggle = QCheckBox(window.workspaces.toggle.text())
        self.toggle.setToolTip(window.workspaces.toggle.toolTip())
        self.toggle.toggled.connect(lambda checked: window.workspaces.switch('edit' if checked else 'read'))
        layout.addWidget(self.toggle)
        self.overlay.hide()
        self.deferred = QTimer(self); self.deferred.setSingleShot(True)
        self.deferred.timeout.connect(self.update_hover)
        # Native video surfaces can consume pointer events before QWidget filters see them.
        self.pointer_check = QTimer(self); self.pointer_check.setInterval(60)
        self.pointer_check.timeout.connect(self.update_hover)
        self.dock.visibilityChanged.connect(self.schedule)
        QApplication.instance().installEventFilter(self)
        self.schedule()

    def close(self):
        QApplication.instance().removeEventFilter(self)
        self.dock.visibilityChanged.disconnect(self.schedule)
        self.deferred.stop()
        self.pointer_check.stop()
        self.overlay.hide()

    def schedule(self, *args):
        if not self.deferred.isActive(): self.deferred.start(0)

    def zone(self):
        w = self.window
        bottom = w.centralWidget().geometry().bottom()+1
        size = self.overlay.sizeHint()
        return QRect(w.centralWidget().geometry().left()+8, max(0, bottom-size.height()-6), size.width(), size.height())

    def update_hover(self, point=None):
        w = self.window
        if not isValid(w): self.pointer_check.stop(); return
        hidden = self.dock.isHidden()
        tracking = hidden and w.isVisible() and not w.isMinimized() and not w.video_fullscreen
        if tracking and not self.pointer_check.isActive(): self.pointer_check.start()
        elif not tracking: self.pointer_check.stop()
        with QSignalBlocker(self.toggle): self.toggle.setChecked(w.workspaces.mode == 'edit')
        area = self.zone(); self.overlay.setGeometry(area)
        point = w.mapFromGlobal(QCursor.pos()) if point is None else point
        visible = tracking and area.contains(point)
        if QApplication.activeModalWidget() is not None: visible = False
        self.overlay.setVisible(visible)
        if visible: self.overlay.raise_()

    def eventFilter(self, obj, event):
        if not isValid(self.window): return False
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.Leave,
                            QEvent.Type.MouseButtonRelease, QEvent.Type.Show, QEvent.Type.Hide,
                            QEvent.Type.Resize, QEvent.Type.Move):
            if isinstance(obj, QWidget) and (obj is self.window or self.window.isAncestorOf(obj)):
                if obj is not self.overlay: self.schedule()
        return False
