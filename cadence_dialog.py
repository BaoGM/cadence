# SPDX-License-Identifier: GPL-3.0-only
from fractions import Fraction
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QComboBox,QCheckBox,QDialogButtonBox
from cadence_change import rate,change_ratio,rounded,media_speed,settings
from ui_text import tr


class CadenceDialog(QDialog):
    def __init__(self,parent,ranges):
        super().__init__(parent); self.setWindowTitle(tr('Changer la cadence')); self.setMinimumWidth(490)
        self.document=parent.doc; self.ranges=ranges
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,18); layout.setSpacing(14)
        media=parent.doc.media[ranges[0][2]]
        title=QLabel(media['name'] if len(ranges)==1 else tr('Plusieurs clips')); title.setTextFormat(Qt.TextFormat.PlainText); title.setWordWrap(True); title.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(title)
        form=QFormLayout(); form.setHorizontalSpacing(18); form.setVerticalSpacing(12); layout.addLayout(form)
        source_rates=sorted(set(Fraction(parent.doc.media[key].get('original_fps',parent.doc.media[key]['fps'])) for _,_,key in ranges))
        form.addRow(tr('Cadence source'),QLabel(' / '.join(f'{float(value):g}' for value in source_rates)+' '+tr('images/s')))
        form.addRow(tr('Cadence de la timeline'),QLabel(f'{float(parent.doc.fps):g} '+tr('images/s')))
        self.rate=QComboBox(); self.rate.setEditable(True)
        self.rate.addItems(['12','15','23.976','24','25','29.97','30','48','50','59.94','60','120'])
        self.rate.setCurrentText(f"{float(Fraction(media.get('cadence',{}).get('rate',media.get('original_fps',media['fps'])))):g}"); form.addRow(tr('Nouvelle cadence'),self.rate)
        self.mode=QComboBox(); self.mode.addItem(tr('Conserver la durée'),'duration'); self.mode.addItem(tr('Accélérer ou ralentir'),'speed'); form.addRow(tr('Traitement'),self.mode)
        self.pitch=QCheckBox(tr('Conserver la hauteur du son')); self.pitch.setChecked(True); layout.addWidget(self.pitch)
        self.summary=QLabel(); self.summary.setWordWrap(True); self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(self.summary)
        info=QLabel(tr('La cadence de la timeline reste inchangée. Le son suit la durée du clip. Les dessins liés suivent le changement ; les clés qui se rejoignent sont regroupées.'))
        info.setWordWrap(True); layout.addWidget(info)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); self.buttons.setCenterButtons(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('&OK'); self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True); self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('&'+tr('Annuler'))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).clicked.connect(self.accept); self.buttons.rejected.connect(self.reject); layout.addWidget(self.buttons)
        self.rate.currentTextChanged.connect(self.update_summary); self.mode.currentIndexChanged.connect(self.update_summary); self.update_summary()

    def update_summary(self):
        self.pitch.setEnabled(self.mode.currentData()=='speed')
        try:
            target=rate(self.rate.currentText())
        except (ValueError,ZeroDivisionError):
            self.summary.setText(tr('Saisir une cadence entre 1 et 240 images/s.')); self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False); return
        try:
            total=0; old=0
            for a,b,key in self.ranges:
                ratio=change_ratio(self.document.media[key],target,self.mode.currentData())
                settings(dict(rate=str(target),speed=str(media_speed(self.document.media[key])/ratio)))
                total+=max(1,rounded((b-a)*ratio)); old+=b-a
            self.summary.setText(tr('Durée sélectionnée')+f' : {float(old/self.document.fps):.3f} s → {float(total/self.document.fps):.3f} s')
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except ValueError as error:
            self.summary.setText(tr(str(error))); self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def values(self): return rate(self.rate.currentText()),self.mode.currentData(),self.pitch.isChecked()
