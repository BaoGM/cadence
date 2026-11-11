# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import sys
from PySide6.QtCore import Qt,Signal,QSize,QPointF
from PySide6.QtGui import QFont,QFontDatabase,QPainter,QPen,QColor
from PySide6.QtWidgets import QComboBox

FAMILIES=('Comic Neue','Dancing Script','Noto Sans','Noto Sans Mono','Noto Serif','Oswald')
_font_ids=[]

def load_fonts():
    if _font_ids: return
    folder=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets/fonts'
    for path in sorted(folder.rglob('*.ttf')):
        identifier=QFontDatabase.addApplicationFont(str(path))
        if identifier>=0: _font_ids.append(identifier)


class DrawingFontCombo(QComboBox):
    currentFontChanged=Signal(QFont)
    def __init__(self):
        super().__init__(); load_fonts(); self.setMaxVisibleItems(10)
        from ui_text import tr
        self.setAccessibleName(tr('Police du texte')); self.setMinimumWidth(160)
        self.setStyleSheet('QComboBox::down-arrow { image:none; }')
        for family in FAMILIES: self.add_family(family)
        self.setCurrentFont(QFont('Noto Sans'))
        self.currentIndexChanged.connect(self.changed)
    def add_family(self,family):
        self.addItem(family); index=self.count()-1
        self.setItemData(index,QFont(family,12),Qt.ItemDataRole.FontRole)
        self.setItemData(index,QSize(220,32),Qt.ItemDataRole.SizeHintRole)
    def currentFont(self): return QFont(self.currentText())
    def setCurrentFont(self,font):
        family=font.family(); index=self.findText(family)
        # Preserve the font named by an older project without offering all
        # installed fonts as if their redistribution rights were known.
        if index<0: self.add_family(family); index=self.count()-1
        self.setCurrentIndex(index)
    def changed(self): self.currentFontChanged.emit(self.currentFont())
    def paintEvent(self,event):
        super().paintEvent(event)
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#c9d5df'),1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        x,y=self.width()-12,self.height()/2
        p.drawLine(QPointF(x-3,y-2),QPointF(x,y+1)); p.drawLine(QPointF(x,y+1),QPointF(x+3,y-2)); p.end()
