# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import QKeySequenceEdit,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton
from dialogs import ButtonStyle
from ui_text import tr


class ShortcutEdit(QKeySequenceEdit):
    def __init__(self):
        super().__init__(); self.setMaximumSequenceLength(1); self.blink=True
        self.caret=QLabel('_',self); self.caret.setStyleSheet('background:transparent;color:#68e0cf;font-weight:bold;'); self.caret.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); self.caret.resize(14,20); self.caret.hide()
        self.blink_timer=QTimer(self); self.blink_timer.setInterval(500); self.blink_timer.timeout.connect(self.flash)
    def flash(self): self.blink=not self.blink; self.caret.setVisible(self.hasFocus() and self.blink)
    def focusInEvent(self,event):
        super().focusInEvent(event); self.blink=True; self.blink_timer.start(); self.setStyleSheet('QLineEdit {background:#243e46;border:1px solid #68e0cf;}'); self.caret.move(self.width()-25,(self.height()-20)//2); self.caret.raise_(); self.caret.show()
    def focusOutEvent(self,event):
        self.blink_timer.stop(); self.caret.hide(); self.setStyleSheet(''); super().focusOutEvent(event); self.update()


class ConflictDialog(QDialog):
    def __init__(self,parent,conflicts):
        super().__init__(parent); self.setWindowTitle(tr('Conflit de raccourcis')); self.setMinimumWidth(420)
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,18); layout.setSpacing(18)
        text=QLabel(tr('Cette combinaison est déjà utilisée :')+'\n\n'+'\n'.join(tr(key) for key in conflicts)); text.setTextFormat(Qt.TextFormat.PlainText); text.setWordWrap(True); text.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(text)
        row=QHBoxLayout(); row.setSpacing(12); layout.addLayout(row); self.button_style=ButtonStyle('Fusion'); self.button_style.setParent(self)
        for title,callback in [('Réattribuer',self.accept),('Annuler',self.reject)]:
            label=tr(title); button=QPushButton('&'+label); button.setStyle(self.button_style); button.setMinimumWidth(150); button.clicked.connect(callback); row.addWidget(button,1)
            shortcut=QShortcut(QKeySequence(label[0]),self); shortcut.setAutoRepeat(False); shortcut.activated.connect(button.click)
            if title=='Annuler': button.setDefault(True)
