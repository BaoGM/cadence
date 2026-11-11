# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QComboBox, QCheckBox, QLabel, QPushButton, QDialogButtonBox, QGroupBox, QWidget)
from widgets import ScrubSpinBox
from ui_text import tr


class SyncDialog(QDialog):
    def __init__(self, link, parent):
        super().__init__(parent)
        self.link = link
        self.setWindowTitle(tr('Synchronisation 3D'))
        self.resize(540, 300)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.enabled = QCheckBox(tr('Activer la synchronisation'))
        self.enabled.toggled.connect(link.set_enabled)
        layout.addWidget(self.enabled)
        form = QFormLayout()
        form.setHorizontalSpacing(20)
        self.host = QComboBox()
        self.host.addItem(tr('Choisir un logiciel…'), None)
        for text, value in (('Blender', 'blender'), ('Maya', 'maya')):
            self.host.addItem(text, value)
        self.direction = QComboBox()
        for text, value in (('Dans les deux sens', 'both'), ('Logiciel 3D vers Cadence', 'receive'), ('Cadence vers logiciel 3D', 'send')):
            self.direction.addItem(tr(text), value)
        self.offset = ScrubSpinBox()
        self.offset.setRange(-10000000, 10000000)
        form.addRow(tr('Logiciel'), self.host)
        form.addRow(tr('Sens'), self.direction)
        form.addRow(tr('Décalage (images Cadence)'), self.offset)
        layout.addLayout(form)
        self.from_start = QCheckBox(tr('Utiliser le début de la plage 3D comme origine'))
        layout.addWidget(self.from_start)
        cadence_row = QHBoxLayout()
        cadence_row.addWidget(QLabel(tr('Adapter la cadence')))
        self.adapt = QPushButton(tr('Média courant…'))
        self.adapt.clicked.connect(lambda:link.adapt_current())
        self.adapt_all = QPushButton(tr('Tous les médias…'))
        self.adapt_all.clicked.connect(lambda:link.adapt_current(True))
        cadence_row.addWidget(self.adapt,1)
        cadence_row.addWidget(self.adapt_all,1)
        layout.addLayout(cadence_row)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.drawings=QGroupBox(tr('Dessins vers le logiciel 3D'))
        drawing_layout=QVBoxLayout(self.drawings)
        drawing_fields=QWidget(); drawing_fields.setMinimumHeight(76)
        drawing_form=QFormLayout(drawing_fields); drawing_form.setContentsMargins(0,0,0,0)
        drawing_form.setHorizontalSpacing(20); drawing_form.setVerticalSpacing(8)
        self.camera=QComboBox()
        self.camera.setMinimumHeight(34)
        camera_row=QHBoxLayout(); camera_row.setSpacing(6); camera_row.addWidget(self.camera,1)
        refresh=QPushButton(tr('Actualiser')); refresh.setMinimumHeight(34); refresh.clicked.connect(link.refresh_cameras); camera_row.addWidget(refresh)
        drawing_form.addRow(tr('Caméra'),camera_row)
        self.drawing_mode=QComboBox()
        self.drawing_mode.setMinimumHeight(34)
        drawing_form.addRow(tr('Format'),self.drawing_mode)
        drawing_layout.addWidget(drawing_fields)
        self.onion=QCheckBox(tr('Inclure les pelures d’oignon'))
        self.onion.setChecked(link.window.drawing.onion.isChecked() if hasattr(link.window,'drawing') else False)
        if hasattr(link.window,'drawing'): link.window.drawing.onion.toggled.connect(self.refresh)
        drawing_layout.addWidget(self.onion)
        self.send=QPushButton(tr('Envoyer les dessins'))
        self.send.clicked.connect(lambda:link.send_drawings(self.camera.currentData(),self.drawing_mode.currentData(),self.onion.isChecked()))
        drawing_layout.addWidget(self.send)
        self.remove=QPushButton(tr('Supprimer les dessins…'))
        self.remove.clicked.connect(link.remove_drawings)
        drawing_layout.addWidget(self.remove)
        layout.addWidget(self.drawings)
        layout.addStretch()
        buttons = QHBoxLayout(); buttons.addStretch()
        close = QPushButton(tr('Fermer')); close.clicked.connect(self.hide)
        buttons.addWidget(close); buttons.addStretch(); layout.addLayout(buttons)
        self.refresh()
        for control, signal in ((self.host, self.host.currentIndexChanged), (self.direction, self.direction.currentIndexChanged),
                                (self.offset, self.offset.valueChanged), (self.from_start, self.from_start.toggled)):
            signal.connect(self.configure)
        link.changed.connect(self.refresh)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.drawings.setMinimumHeight(self.drawings.layout().totalHeightForWidth(self.drawings.width()))

    def configure(self, *args):
        self.link.configure(self.host.currentData(), self.direction.currentData(), self.offset.value(), self.from_start.isChecked())

    def refresh(self):
        link = self.link
        for control, value, method in ((self.enabled, link.enabled, 'setChecked'),
                (self.host, self.host.findData(link.host), 'setCurrentIndex'),
                (self.direction, self.direction.findData(link.direction), 'setCurrentIndex'),
                (self.offset, link.offset, 'setValue'), (self.from_start, link.from_start, 'setChecked')):
            with QSignalBlocker(control): getattr(control, method)(value)
        self.status.setText(tr(link.status))
        self.adapt.setEnabled(link.metadata is not None)
        self.adapt_all.setEnabled(link.metadata is not None)
        host=link.host
        if self.drawings.property('host')!=host:
            self.drawings.setProperty('host',host)
            self.drawing_mode.clear()
            if host=='blender': self.drawing_mode.addItem('Grease Pencil','native')
            if host=='maya': self.drawing_mode.addItem(tr('Blue Pencil'),'blue_pencil')
            self.drawing_mode.addItem(tr('Images transparentes'),'images')
            self.drawings.setTitle(tr('Dessins vers Blender') if host=='blender' else tr('Dessins vers Maya') if host=='maya' else tr('Dessins vers le logiciel 3D'))
        current=self.camera.currentData()
        if [self.camera.itemData(i) for i in range(self.camera.count())]!=link.cameras:
            self.camera.clear()
            for name in link.cameras: self.camera.addItem(name,name)
            if current in link.cameras: self.camera.setCurrentIndex(self.camera.findData(current))
        self.drawings.setEnabled(bool(link.metadata and link.drawing_capability and not link.drawing_request and not link.window.job))
        self.onion.setEnabled(hasattr(link.window,'drawing') and link.window.drawing.onion.isChecked())
        self.send.setEnabled(bool(link.cameras and not link.drawing_request and not link.window.job))
        self.remove.setEnabled(bool(getattr(link,'drawing_removal',False) and not link.drawing_request and not link.window.job))
        if self.isVisible():
            self.drawings.setMinimumHeight(self.drawings.layout().totalHeightForWidth(self.drawings.width()))


def choose_host(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr('Choisir le logiciel 3D'))
    dialog.setMinimumWidth(340)
    layout = QVBoxLayout(dialog)
    label = QLabel(tr('Quel logiciel souhaitez-vous synchroniser ?'))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(label)
    choices = QComboBox()
    choices.addItem(tr('Choisir un logiciel…'), None)
    choices.addItem('Blender', 'blender')
    choices.addItem('Maya', 'maya')
    layout.addWidget(choices)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.setCenterButtons(True)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
    choices.currentIndexChanged.connect(lambda: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(choices.currentData() is not None))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return choices.currentData() if dialog.exec() == QDialog.DialogCode.Accepted else None
