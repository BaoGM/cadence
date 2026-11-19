# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt, QRectF, QRect, QEvent, QTimer
from PySide6.QtGui import QPainter, QColor, QShortcut, QKeySequence, QCursor, QIcon, QPixmap, QPen
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QHBoxLayout, QToolButton, QLabel, QSlider, QStyle, QMenu

from ui_text import tr


def overlay_icon(style, symbol):
    pixmap = style.standardIcon(symbol).pixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor('#e8edf5')); painter.end()
    return QIcon(pixmap)


class MirrorCanvas(QWidget):
    def __init__(self, source, parent):
        super().__init__(parent)
        self.source = source
        self.setMinimumSize(160, 90)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        source.presentationChanged.connect(self.update)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor('#0c0f14'))
            source = self.source
            if not source.width() or not source.height(): return
            size = source.image_size().scaled(source.size(), Qt.AspectRatioMode.KeepAspectRatio) if source.image else source.size()
            scale = min(self.width() / max(1, size.width()), self.height() / max(1, size.height()))
            painter.setClipRect(QRectF(self.rect()))
            painter.translate((self.width() - source.width() * scale) / 2,
                              (self.height() - source.height() * scale) / 2)
            painter.scale(scale, scale)
            source.paint_scene(painter, sample=True)
        finally:
            painter.end()

    def contextMenuEvent(self, event):
        menu = self.parentWidget().context_menu()
        menu.exec(event.globalPos()); menu.deleteLater()


class VideoMirror(QDialog):
    def __init__(self, window, action):
        # An owned native window raises its owner when activated on Windows.
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        window.destroyed.connect(self.deleteLater)
        self.main_window = window
        self.window_drag = None
        self.keyboard_controls = False
        self.setWindowTitle(tr('Aperçu vidéo indépendant'))
        self.setModal(False)
        self.setMinimumSize(320, 180)
        self.resize(800, 450)
        self.action = action
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas = MirrorCanvas(window.viewer, self)
        layout.addWidget(self.canvas, 1)
        self.controls = QWidget(self.canvas)
        self.controls.setObjectName('mirrorControls')
        self.controls.setStyleSheet('#mirrorControls {background:rgba(15,21,29,220);border-radius:7px;} QToolButton {border:0;background:transparent;padding:5px;} QToolButton:hover,QToolButton:checked {background:#354752;border-radius:4px;}')
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(6)
        self.play = QToolButton()
        self.play.setToolTip(tr('Lecture / pause'))
        self.play.setAccessibleName(tr('Lecture / pause'))
        self.play.clicked.connect(window.toggle_play)
        self.play_icons = {False: overlay_icon(self.style(), QStyle.StandardPixmap.SP_MediaPlay),
                           True: overlay_icon(self.style(), QStyle.StandardPixmap.SP_MediaPause)}
        row.addWidget(self.play)
        self.on_top = QToolButton()
        self.on_top.setCheckable(True)
        self.on_top.setToolTip(tr('Toujours au premier plan'))
        self.on_top.setAccessibleName(tr('Toujours au premier plan'))
        pin = QPixmap(48, 48); pin.setDevicePixelRatio(2); pin.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pin); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#e8edf5'), 1.5))
        painter.drawLine(8, 4, 16, 4); painter.drawLine(9, 4, 9, 10); painter.drawLine(15, 4, 15, 10)
        painter.drawLine(9, 10, 6, 14); painter.drawLine(15, 10, 18, 14); painter.drawLine(6, 14, 18, 14)
        painter.drawLine(12, 14, 12, 21); painter.end()
        self.on_top.setIcon(QIcon(pin))
        self.on_top.toggled.connect(self.set_on_top)
        row.addWidget(self.on_top)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(100)
        self.opacity.setToolTip(tr('Opacité'))
        self.opacity.setAccessibleName(tr('Opacité'))
        self.opacity.setMinimumWidth(60)
        self.opacity.setMaximumWidth(140)
        self.opacity.valueChanged.connect(lambda value: self.setWindowOpacity(value / 100))
        row.addWidget(self.opacity, 1)
        self.opacity_label = QLabel('100 %')
        self.opacity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.opacity_label.setFixedWidth(44)
        self.opacity.valueChanged.connect(lambda value: self.opacity_label.setText(f'{value} %'))
        row.addWidget(self.opacity_label)
        self.close_button = QToolButton()
        self.close_button.setIcon(overlay_icon(self.style(), QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_button.setToolTip(tr('Fermer'))
        self.close_button.setAccessibleName(tr('Fermer'))
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        for button in (self.play, self.on_top, self.close_button): button.setFixedSize(32, 34)
        self.controls.hide()
        for widget in (self.canvas, self.controls, *self.controls.findChildren(QWidget)):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        window.viewer.presentationChanged.connect(self.update_play_button)
        self.play.clicked.connect(self.update_play_button)
        self.update_play_button()
        shortcut = QShortcut(QKeySequence('Space'), self)
        shortcut.activated.connect(window.toggle_play)

    def update_play_button(self):
        playing = self.main_window.transport.running
        if self.play.property('playing') != playing:
            self.play.setProperty('playing', playing)
            self.play.setIcon(self.play_icons[playing])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'controls'): return
        width = min(360, self.width() - 16)
        self.controls.setGeometry((self.width()-width)//2, self.height()-52, width, 44)

    def update_controls(self, point=None):
        if point is None: point = self.canvas.mapFromGlobal(QCursor.pos())
        active = self.opacity.isSliderDown() or any(button.isDown() for button in (self.play, self.on_top, self.close_button))
        focused = bool(self.keyboard_controls and self.focusWidget() and self.controls.isAncestorOf(self.focusWidget()))
        hover = self.controls.geometry().contains(point) and self.canvas.rect().contains(point)
        self.controls.setVisible(not self.window_drag and (hover or active or focused))

    def edges_at(self, point):
        edges = Qt.Edge(0)
        if point.x() < 6: edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width()-6: edges |= Qt.Edge.RightEdge
        if point.y() < 6: edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height()-6: edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self.update_controls)
        if kind == QEvent.Type.FocusIn and obj is not self.canvas:
            if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason): self.keyboard_controls = True
            self.controls.show()
        if kind == QEvent.Type.MouseButtonPress: self.keyboard_controls = False
        if kind == QEvent.Type.MouseMove:
            point = self.canvas.mapFromGlobal(event.globalPosition().toPoint())
            if self.window_drag:
                edges, origin, geometry = self.window_drag
                delta = event.globalPosition().toPoint()-origin
                target = QRect(geometry)
                if not edges: target.moveTopLeft(geometry.topLeft()+delta)
                else:
                    if edges & Qt.Edge.LeftEdge: target.setLeft(min(geometry.right()-self.minimumWidth()+1, geometry.left()+delta.x()))
                    if edges & Qt.Edge.RightEdge: target.setRight(max(geometry.left()+self.minimumWidth()-1, geometry.right()+delta.x()))
                    if edges & Qt.Edge.TopEdge: target.setTop(min(geometry.bottom()-self.minimumHeight()+1, geometry.top()+delta.y()))
                    if edges & Qt.Edge.BottomEdge: target.setBottom(max(geometry.top()+self.minimumHeight()-1, geometry.bottom()+delta.y()))
                self.setGeometry(target); event.accept(); return True
            self.update_controls(point)
            if obj is self.canvas:
                edges = self.edges_at(point)
                diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
                both = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)) and bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
                cursor = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor if both else Qt.CursorShape.SizeHorCursor if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge) else Qt.CursorShape.SizeVerCursor if edges else Qt.CursorShape.ArrowCursor
                self.canvas.setCursor(cursor)
        if obj is self.canvas and kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.canvas.setFocus(); edges = self.edges_at(event.position().toPoint())
            handle = self.windowHandle()
            native = handle and (handle.startSystemResize(edges) if edges else handle.startSystemMove())
            if not native: self.window_drag = (edges, event.globalPosition().toPoint(), self.geometry())
            self.controls.hide(); event.accept(); return True
        if kind == QEvent.Type.MouseButtonRelease:
            moving = self.window_drag is not None; self.window_drag = None
            QTimer.singleShot(0, self.update_controls)
            if moving: event.accept(); return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close(); event.accept(); return
        if event.key() == Qt.Key.Key_Tab and not self.controls.isVisible():
            self.keyboard_controls = True; self.controls.show(); self.play.setFocus(Qt.FocusReason.TabFocusReason); event.accept(); return
        super().keyPressEvent(event)

    def context_menu(self):
        menu = QMenu(self)
        menu.addAction(tr('Lecture / pause'), self.main_window.toggle_play)
        action = menu.addAction(tr('Toujours au premier plan'))
        action.setCheckable(True); action.setChecked(self.on_top.isChecked())
        action.toggled.connect(self.on_top.setChecked)
        menu.addSeparator(); menu.addAction(tr('Fermer'), self.close)
        return menu

    def set_on_top(self, enabled):
        geometry = self.saveGeometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.restoreGeometry(geometry)
        self.show()

    def closeEvent(self, event):
        self.action.setChecked(False)
        super().closeEvent(event)


def toggle(window, checked):
    if checked:
        if not getattr(window, 'video_mirror', None):
            window.video_mirror = VideoMirror(window, window.video_mirror_action)
        window.video_mirror.show()
        window.video_mirror.raise_()
    elif getattr(window, 'video_mirror', None):
        window.video_mirror.hide()
