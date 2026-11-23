# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QWidget


class HandleFocus(QWidget):
    def __init__(self, host, valid, nudge, cycle=None, cancel=None):
        super().__init__(host)
        self.valid, self.nudge = valid, nudge
        self.cycle, self.cancel = cycle, cancel
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.ClickFocus)
        self.resize(1, 1)

    def activate(self, name):
        self.setAccessibleName(name)
        self.show()
        self.setFocus(Qt.OtherFocusReason)
        self.parentWidget().update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.hide()
        self.parentWidget().update()

    def event(self, event):
        kind = event.type()
        if kind not in (QEvent.ShortcutOverride, QEvent.KeyPress) or not self.hasFocus():
            return super().event(event)
        key, mods = event.key(), event.modifiers()
        tab = key in (Qt.Key_Backtab, Qt.Key_Tab) and mods in (Qt.NoModifier, Qt.ShiftModifier)
        keys = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Escape, Qt.Key_Enter, Qt.Key_Return)
        if not tab and (mods != Qt.NoModifier or key not in keys):
            return super().event(event)
        if not self.valid():
            self.parentWidget().setFocus()
            return False
        event.accept()
        if kind == QEvent.ShortcutOverride:
            return True
        if key in (Qt.Key_Left, Qt.Key_Right):
            self.nudge(1 if key == Qt.Key_Right else -1)
        elif tab:
            forward = key == Qt.Key_Tab and mods == Qt.NoModifier
            if not self.cycle or not self.cycle(1 if forward else -1):
                host = self.parentWidget()
                host.setFocus()
                host.focusNextPrevChild(forward)
        else:
            if key == Qt.Key_Escape and self.cancel:
                self.cancel()
            self.parentWidget().setFocus()
        return True
