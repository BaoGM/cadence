# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget

from studio_icons import icon
from ui_text import tr


class PreferencesScroll(QScrollArea):
    def __init__(self, columns):
        super().__init__()
        self.columns = columns

    def resizeEvent(self, event):
        direction = QBoxLayout.Direction.TopToBottom if event.size().width() < 565 else QBoxLayout.Direction.LeftToRight
        self.columns.setDirection(direction)
        super().resizeEvent(event)


def scroll_page(page, columns):
    scroll = PreferencesScroll(columns)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    return scroll


def build_options_layout(dialog, tabs):
    dialog.setObjectName('studioOptions')
    dialog.setStyleSheet("""
        QDialog#studioOptions, QDialog#studioOptions QTabWidget::pane,
        QDialog#studioOptions QScrollArea, QDialog#studioOptions QGroupBox {background:#191f27;}
        QDialog#studioOptions QWidget#optionsRail {background:#151a21;border-right:1px solid #343e48;}
        QDialog#studioOptions QWidget#optionsPreferences {background:#191f27;}
        QDialog#studioOptions QLabel, QDialog#studioOptions QCheckBox {background:transparent;}
        QDialog#studioOptions QScrollBar:vertical {width:8px;background:#161c23;border:0;}
        QDialog#studioOptions QScrollBar::handle:vertical {min-height:20px;background:#485764;border-radius:3px;}
        QDialog#studioOptions QScrollBar::add-line:vertical, QDialog#studioOptions QScrollBar::sub-line:vertical {height:0;}
        QDialog#studioOptions QScrollBar::add-page:vertical, QDialog#studioOptions QScrollBar::sub-page:vertical {background:transparent;}
        QDialog#studioOptions QPushButton#optionsApply {background:#68e0cf;color:#102725;font-weight:600;border:0;}
        QDialog#studioOptions QPushButton#optionsApply:hover {background:#85e9d9;}
        QDialog#studioOptions QPushButton#optionsApply:pressed {background:#53bfb0;}
        QDialog#studioOptions QLabel#optionsTitle {color:#edf3f6;font-size:17px;font-weight:600;padding:8px 6px 13px;}
        QDialog#studioOptions QToolButton#optionsSection {border:1px solid transparent;text-align:left;background:transparent;color:#b4c1cf;padding:4px 8px;border-radius:4px;}
        QDialog#studioOptions QToolButton#optionsSection:hover {background:#2a3542;}
        QDialog#studioOptions QToolButton#optionsSection:pressed {background:#334151;}
        QDialog#studioOptions QToolButton#optionsSection:checked {background:#213538;color:#77e0d2;border:1px solid #355454;}
        QDialog#studioOptions QGroupBox {border:0;border-top:1px solid #37434c;border-radius:0;margin-top:11px;padding:12px 1px 0;color:#c5d1dc;font-weight:600;}
        QDialog#studioOptions QGroupBox::title {subcontrol-origin:margin;left:0;top:0;padding:0 8px 0 0;}
        QDialog#studioOptions QTabWidget::pane {border:0;}
        QDialog#studioOptions QTableWidget {gridline-color:#313d47;selection-background-color:#274342;}
    """)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(0,0,0,10)
    body = QHBoxLayout()
    body.setSpacing(0)
    rail = QWidget()
    rail.setObjectName('optionsRail')
    nav = QVBoxLayout(rail)
    nav.setContentsMargins(9,12,9,10)
    nav.setSpacing(5)
    title = QLabel(tr('Options'))
    title.setObjectName('optionsTitle')
    nav.addWidget(title)
    group = QButtonGroup(rail)
    tabs.tabBar().hide()
    for idx, (symbol, text) in enumerate((('settings','Préférences'),('keyboard','Raccourcis'),('cursor','Vue et navigation'))):
        button = QToolButton()
        button.setObjectName('optionsSection')
        button.setText(tr(text))
        button.setIcon(icon(symbol))
        button.setIconSize(QSize(17,17))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setCheckable(True)
        button.setMinimumHeight(32)
        group.addButton(button, idx)
        nav.addWidget(button)
        button.setChecked(idx == 0)
    group.idClicked.connect(tabs.setCurrentIndex)
    tabs.currentChanged.connect(lambda index: group.button(index).setChecked(True) if group.button(index) else None)
    nav.addStretch()
    body.addWidget(rail)
    body.addWidget(tabs, 1)
    root.addLayout(body, 1)
    return root
