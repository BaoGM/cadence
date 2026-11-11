# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QObject,QEvent,QTimer
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QProxyStyle,QStyle,QDialogButtonBox,QMessageBox,QInputDialog
from ui_text import tr

class ButtonStyle(QProxyStyle):
    def styleHint(self,hint,option=None,widget=None,returnData=None):
        if hint==QStyle.StyleHint.SH_UnderlineShortcut: return 1
        return super().styleHint(hint,option,widget,returnData)

class ConfirmationDialog(QDialog):
    def __init__(self,parent,title,question,detail='',cancel=False):
        super().__init__(parent); self.setWindowTitle(title); self.setMinimumWidth(380)
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,18); layout.setSpacing(18)
        for text in (question,detail):
            if text:
                label=QLabel(text); label.setTextFormat(Qt.TextFormat.PlainText); label.setWordWrap(True); label.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(label)
        row=QHBoxLayout(); row.setSpacing(10); layout.addLayout(row)
        self.buttons={}; self.button_style=ButtonStyle('Fusion'); self.button_style.setParent(self)
        choices=[('yes',tr('Oui'),1),('no',tr('Non'),2)]
        if cancel: choices.append(('cancel',tr('Annuler'),0))
        for name,text,result in choices:
            button=QPushButton('&'+text); button.setStyle(self.button_style); row.addWidget(button,1); self.buttons[name]=button
            button.clicked.connect(lambda checked=False,value=result:self.done(value))
        self.buttons['yes'].setDefault(True)

    def keyPressEvent(self,event):
        if event.modifiers()==Qt.KeyboardModifier.NoModifier and not event.isAutoRepeat():
            for button in self.buttons.values():
                if event.text().casefold()==button.text().replace('&','')[0].casefold():
                    button.click(); event.accept(); return
        super().keyPressEvent(event)

class DialogPresentation(QObject):
    def eventFilter(self,obj,event):
        if event.type()!=QEvent.Type.Show: return False
        if isinstance(obj,QPushButton) and isinstance(obj.window(),QDialog): self.button(obj)
        if not isinstance(obj,QDialog): return False
        for box in obj.findChildren(QDialogButtonBox): box.setCenterButtons(True)
        for button in obj.findChildren(QPushButton): self.button(button)
        if isinstance(obj,(QMessageBox,QInputDialog)):
            for label in obj.findChildren(QLabel):
                if label.pixmap() is None or label.pixmap().isNull():
                    label.setAlignment(Qt.AlignmentFlag.AlignCenter); label.setWordWrap(True)
        if isinstance(obj,QMessageBox) and obj.icon() in (QMessageBox.Icon.Warning,QMessageBox.Icon.Critical):
            import logging,sys
            logging.warning('Dialog %s: %s %s',obj.windowTitle(),obj.text(),obj.informativeText(),exc_info=sys.exc_info()[0] is not None)
        if not obj.property('cadenceCentered') and not obj.windowFlags()&Qt.WindowType.FramelessWindowHint:
            obj.setProperty('cadenceCentered',True)
            QTimer.singleShot(0,obj,lambda:self.center(obj))
        return False
    def button(self,button):
        text=button.text()
        if text and '&' not in text and any(c.isalpha() for c in text):
            index=next(i for i,c in enumerate(text) if c.isalpha())
            button.setText(text[:index]+'&'+text[index:])
    def center(self,dialog):
        if not dialog.isVisible(): return
        parent=dialog.parentWidget(); screen=dialog.screen().availableGeometry()
        center=parent.window().frameGeometry().center() if parent and parent.isVisible() else screen.center()
        frame=dialog.frameGeometry(); frame.moveCenter(center)
        frame.moveLeft(max(screen.left(),min(frame.left(),screen.right()-frame.width()+1)))
        frame.moveTop(max(screen.top(),min(frame.top(),screen.bottom()-frame.height()+1)))
        dialog.move(frame.topLeft())

def install_dialog_presentation():
    app=QApplication.instance()
    if hasattr(app,'cadence_dialog_presentation'): return
    app.cadence_dialog_presentation=DialogPresentation(app)
    app.installEventFilter(app.cadence_dialog_presentation)
