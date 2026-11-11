# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import Qt,QPoint,QLocale
from PySide6.QtTest import QTest
from test_drawing import application,window

@pytest.mark.parametrize('tool',['cursor','brush','eraser','lasso','text','arrow','rectangle','ellipse'])
def test_sensitivity_entry_with_every_tool(window,application,tool):
    d=window.drawing;d.panel.show();d.choose_tool(tool);application.processEvents()
    spin=d.sensitivity;spin.setLocale(QLocale('fr_FR'));edit=spin.lineEdit()
    assert spin.isEnabled()
    QTest.mouseClick(edit,Qt.MouseButton.LeftButton,pos=QPoint(10,edit.height()//2))
    assert edit.hasFocus() and edit.hasSelectedText()
    QTest.keyClicks(edit,'2,50');QTest.keyClick(edit,Qt.Key.Key_Return)
    assert spin.value()==2.5
    d.choose_tool('brush');assert spin.value()==2.5
