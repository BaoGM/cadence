# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStyle, QStyleOptionFrame

from studio_icons import icon
from ui_text import tr


def inspector_section(layout, symbol, title):
    row = QHBoxLayout()
    row.setSpacing(7)
    glyph = QLabel()
    glyph.setFixedSize(18,18)
    glyph.setPixmap(icon(symbol,'#b5c5d3').pixmap(17,17))
    glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label = QLabel(tr(title))
    label.setObjectName('inspectorSection')
    row.addWidget(glyph)
    row.addWidget(label)
    row.addStretch()
    layout.addLayout(row)


def style_inspector(dialog):
    dialog.setObjectName('studioInspector')
    dialog.setStyleSheet("""
        QDialog#studioInspector {background:#171e26;color:#e3eaf1;}
        QDialog#studioInspector QWidget {color:#e3eaf1;}
        QDialog#studioInspector QLabel, QDialog#studioInspector QCheckBox,
        QDialog#studioInspector QGroupBox, QDialog#studioInspector QGroupBox QWidget {background:transparent;}
        QDialog#studioInspector QLabel#inspectorSection {font-size:13px;font-weight:600;}
        QDialog#studioInspector QGroupBox {border:0;border-top:1px solid #333f4c;border-radius:0;margin-top:10px;padding-top:10px;font-weight:600;}
        QDialog#studioInspector QGroupBox::title {subcontrol-origin:margin;left:0;padding-right:7px;}
        QDialog#studioInspector QPushButton {background:#232d38;border:1px solid #394654;border-radius:5px;padding:5px 9px;}
        QDialog#studioInspector QPushButton:hover {background:#2a3542;border-color:#5b7e82;}
        QDialog#studioInspector QPushButton:pressed {background:#334151;}
        QDialog#studioInspector QPushButton:checked {background:#253f43;border-color:#426164;color:#68e0cf;}
        QDialog#studioInspector QPushButton:disabled {background:#1b222a;color:#76828e;border-color:#303a44;}
        QDialog#studioInspector QComboBox, QDialog#studioInspector QSpinBox, QDialog#studioInspector QLineEdit {
            background:#131a21;color:#e3eaf1;border:1px solid #394654;border-radius:5px;padding:4px 8px;}
    """)
    def fit_placeholders():
        for field in dialog.findChildren(QLineEdit):
            if not field.placeholderText():
                continue
            field.ensurePolished()
            option = QStyleOptionFrame()
            field.initStyleOption(option)
            inner = field.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, field)
            margins = field.textMargins()
            insets = option.rect.width() - inner.width() + margins.left() + margins.right()
            required = field.fontMetrics().horizontalAdvance(field.placeholderText()) + insets + 6
            field.setMinimumWidth(max(field.minimumWidth(),required))
    # The dialog applies its style before creating its input fields.
    QTimer.singleShot(0, dialog, fit_placeholders)
