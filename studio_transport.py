# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QSlider, QToolButton, QWidget

from studio_icons import icon, paint_icon
from ui_text import tr


class TransportButton(QPushButton):
    def __init__(self, symbol, callback, name='transport', tip=''):
        super().__init__()
        self.symbol = symbol
        self.setObjectName(name)
        self.setFixedSize(39 if name == 'primary' else 28, 30)
        self.setStyleSheet('padding:0; border:0;')
        self.clicked.connect(callback)
        self.setToolTip(tr(tip))
        self.setAccessibleName(tr(tip))

    def setSymbol(self, symbol):
        self.symbol = symbol
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        primary = self.objectName() == 'primary' and self.isEnabled()
        keyboard = self.hasFocus() and self.testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange)
        if primary or self.isChecked() or self.underMouse() or self.isDown() or keyboard:
            color = '#68e0cf' if primary else '#253f43' if self.isChecked() else '#334151' if self.isDown() else '#2a3542'
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor('#68e0cf'), 2) if keyboard else Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 5, 5)
        color = QColor('#102725' if primary else '#68e0cf' if self.isChecked() else '#e3eaf1')
        if not self.isEnabled() or self.symbol == 'once':
            color = QColor('#8a99a9')
        p.translate(self.width()/2, self.height()/2)
        p.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        self.draw_symbol(p, color)
        p.end()

    def draw_symbol(self, painter, color):
        paint_icon(painter, QRectF(-9,-9,18,18), 'prev' if self.symbol == 'previous' else self.symbol, color)


class LevelSlider(QSlider):
    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 100)
        self.setSingleStep(5)
        self.setAccessibleName(tr('Volume de lecture'))

    def seek(self, x):
        self.setValue(round(100 * (x - 6) / max(1, self.width() - 12)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setSliderDown(True)
            self.seek(event.position().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.seek(event.position().x())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.isSliderDown() and event.button() == Qt.MouseButton.LeftButton:
            self.seek(event.position().x())
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.parentWidget().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_M:
            self.parentWidget().toggle_mute()
        else:
            super().keyPressEvent(event)


class VolumeBars(QWidget):
    valueChanged = Signal(int)
    mutedChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.muted = False
        self.setFixedSize(130, 32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(3)
        self.speaker = QToolButton()
        self.speaker.setFixedSize(26,28)
        self.speaker.setIconSize(QSize(17,17))
        self.speaker.clicked.connect(self.toggle_mute)
        layout.addWidget(self.speaker)
        self.slider = LevelSlider(self)
        self.slider.setValue(80)
        self.slider.valueChanged.connect(self.level_changed)
        layout.addWidget(self.slider, 1)
        self.readout = QLabel()
        self.readout.setFixedWidth(36)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.readout)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocusProxy(self.slider)
        self.setAccessibleName(tr('Volume de lecture'))
        self.setStyleSheet("""
            QToolButton {background:transparent; border:0; padding:0;}
            QToolButton:hover, QToolButton:focus {background:#2a3542; border-radius:5px;}
            QToolButton:pressed {background:#334151;}
            QLabel {color:#9aaabb; font:11px Consolas, monospace; background:transparent;}
            QSlider::groove:horizontal {height:4px; border-radius:2px; background:#3c4854;}
            QSlider::sub-page:horizontal {background:#68e0cf; border-radius:2px;}
            QSlider::handle:horizontal {width:12px; margin:-4px 0; border-radius:6px; background:#68e0cf;}
            QSlider[muted="true"]::sub-page:horizontal, QSlider[muted="true"]::handle:horizontal {background:#8593a0;}
        """)
        self.refresh()

    def value(self):
        return self.slider.value()

    def setValue(self, value):
        self.slider.setValue(int(value))

    def level_changed(self, value):
        self.refresh()
        self.valueChanged.emit(value)

    def toggle_mute(self):
        self.setMuted(not self.muted)

    def setMuted(self, muted):
        if self.muted != bool(muted):
            self.muted = bool(muted)
            self.slider.setProperty('muted', self.muted)
            self.slider.style().unpolish(self.slider)
            self.slider.style().polish(self.slider)
            self.refresh()
            self.mutedChanged.emit(self.muted)

    def refresh(self):
        self.readout.setText(f'{self.value()} %')
        self.speaker.setIcon(icon('mute' if self.muted or self.value() == 0 else 'sound'))
        action = tr('Unmute' if self.muted else 'Mute')
        self.speaker.setAccessibleName(action)
        self.speaker.setToolTip(action)
        self.setToolTip(tr(f'Volume : {self.value()} %' + (' · Muet' if self.muted else '') + '\nGlisser : volume · Clic droit : Mute / Unmute'))

    def wheelEvent(self, event):
        self.setValue(self.value() + round(event.angleDelta().y()/120)*5)
        event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction(tr('Unmute' if self.muted else 'Mute'), self.toggle_mute)
        menu.exec(event.globalPos())
