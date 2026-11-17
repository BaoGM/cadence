# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtWidgets import QApplication,QWidget


class VolumeShortcut(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window; self.remainder=0.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self,obj,event):
        if event.type()!=QEvent.Type.Wheel or not event.modifiers()&Qt.KeyboardModifier.ControlModifier:
            return False
        if not isinstance(obj,QWidget) or not (obj is self.window or self.window.isAncestorOf(obj)):
            return False
        delta=event.angleDelta().y()/120 if event.angleDelta().y() else event.pixelDelta().y()/40
        self.remainder+=delta
        steps=int(self.remainder)
        if steps:
            self.remainder-=steps
            volume=self.window.volume
            volume.setValue(volume.value()+steps*5)
            if steps>0 and volume.muted: volume.setMuted(False)
        event.accept()
        return True
