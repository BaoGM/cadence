# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout
from ui_text import tr


class DrawingProgress(QDialog):
    def __init__(self,parent,cancel=None):
        super().__init__(parent)
        self.cancel_transfer=cancel
        self.setWindowTitle(tr('Envoyer les dessins'))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint,False)
        layout=QVBoxLayout(self)
        self.label=QLabel(tr('Importation dans le logiciel 3D…'))
        self.bar=QProgressBar()
        layout.addWidget(self.label); layout.addWidget(self.bar)
        self.cancel_button=QPushButton(tr('Annuler'))
        self.cancel_button.setVisible(cancel is not None)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        self.setMinimumWidth(360)

    def setValue(self,value):
        self.bar.setValue(value)

    def reject(self):
        if self.cancel_transfer and self.cancel_button.isEnabled() and self.cancel_transfer():
            self.cancel_button.setEnabled(False)
            self.label.setText(tr('Annulation du transfert…'))
