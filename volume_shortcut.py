# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtWidgets import (QApplication, QWidget, QAbstractButton, QAbstractItemView,
    QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QComboBox, QLineEdit,
    QDialog, QDockWidget, QMenu, QMenuBar, QTabBar)


class VolumeShortcut(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window; self.remainder=0.
        QApplication.instance().installEventFilter(self)

    def adjust(self,steps):
        volume=self.window.volume
        volume.setValue(volume.value()+steps*5)
        if steps>0 and volume.muted: volume.setMuted(False)

    def navigation_uses_arrows(self,widget):
        if QApplication.activePopupWidget() or QApplication.activeModalWidget(): return True
        while widget is not None and widget is not self.window:
            if widget is self.window.viewer or widget is self.window.timeline: return False
            if isinstance(widget,(QAbstractItemView,QAbstractScrollArea,QAbstractSlider,QAbstractSpinBox,
                                  QComboBox,QLineEdit,QTabBar,QMenuBar,QMenu,QDialog)):
                return True
            if isinstance(widget,QAbstractButton) and widget.autoExclusive(): return True
            if isinstance(widget,QDockWidget):
                return widget in (self.window.library,self.window.comparison_panel,self.window.drawing.panel,
                                  self.window.edit_toolbar)
            widget=widget.parentWidget()
        return False

    def eventFilter(self,obj,event):
        if (event.type()==QEvent.Type.ShortcutOverride and event.key() in (Qt.Key_Up, Qt.Key_Down)
                and event.modifiers()==Qt.NoModifier and isinstance(obj,QWidget)
                and self.window.isAncestorOf(obj) and self.navigation_uses_arrows(obj)):
            event.accept()
            return True
        if event.type()!=QEvent.Type.Wheel or not event.modifiers()&Qt.KeyboardModifier.ControlModifier:
            return False
        if not isinstance(obj,QWidget) or not (obj is self.window or self.window.isAncestorOf(obj)):
            return False
        delta=event.angleDelta().y()/120 if event.angleDelta().y() else event.pixelDelta().y()/40
        self.remainder+=delta
        steps=int(self.remainder)
        if steps:
            self.remainder-=steps
            self.adjust(steps)
        event.accept()
        return True
