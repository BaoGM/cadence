# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle
from test_drawing import application,window
from dialogs import ConfirmationDialog

@pytest.mark.parametrize('key,result',[(Qt.Key.Key_O,1),(Qt.Key.Key_N,2),(Qt.Key.Key_A,0),(Qt.Key.Key_Escape,0),(Qt.Key.Key_Return,1)])
def test_confirmation_keyboard(window,application,key,result):
    box=ConfirmationDialog(window,'Projet','Enregistrer les modifications avant de continuer ?',cancel=True)
    assert box.buttons['yes'].style().styleHint(QStyle.StyleHint.SH_UnderlineShortcut)==1
    QTimer.singleShot(50,lambda:QTest.keyClick(box,key))
    timeout=QTimer(box); timeout.setSingleShot(True); timeout.timeout.connect(lambda:box.done(-99)); timeout.start(1000)
    assert box.exec()==result
    box.deleteLater()
