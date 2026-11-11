# SPDX-License-Identifier: GPL-3.0-only
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from test_drawing import application,window
from preferences import ShortcutDialog

@pytest.mark.parametrize('target,key',[('options',Qt.Key.Key_A),('options',Qt.Key.Key_E),('modes',Qt.Key.Key_A),('modes',Qt.Key.Key_O),('help',Qt.Key.Key_F),('about',Qt.Key.Key_O)])
def test_dialog_letter_commands(window,application,target,key):
    timed_out=[]
    timeout=QTimer(); timeout.setSingleShot(True)
    def abort():
        timed_out.append(True); application.activeModalWidget().reject()
    timeout.timeout.connect(abort); timeout.start(2000)
    def press():
        dialog=application.activeModalWidget()
        dialog.activateWindow()
        QTest.qWait(100)
        QTest.keyClick(dialog,key)
    QTimer.singleShot(100,press)
    if target=='options':
        dialog=ShortcutDialog(window.action_registry,window.preferences,window); dialog.exec(); dialog.deleteLater()
    elif target=='modes': window.workspaces.configure()
    else: getattr(window,target)()
    timeout.stop(); assert not timed_out

