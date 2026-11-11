# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from test_drawing import application,window
from test_color1210 import setup_selection

def test_opacity_selection_range_and_undo(window):
 w=window;d=w.drawing;key,other=setup_selection(w);original=w.doc.state;n=len(w.doc.undo_stack)
 d.opacity.scrubbing=True;d.opacity.setValue(60);d.opacity.setValue(35)
 assert w.doc.state==original and d.selection.preview.marks[0].opacity==.35
 d.opacity.scrubbing=False;d.opacity.editingFinished.emit()
 updated=w.doc.state.drawings[0]
 assert (updated.start,updated.end)==(2,15) and w.doc.state.drawings[1]==other
 assert [m.opacity for m in updated.marks]==[.35,.35,.35,1.]
 assert updated.marks[2].children==key.marks[2].children
 assert len(w.doc.undo_stack)==n+1 and d.selection.indices==(0,1,2)
 w.doc.undo();assert w.doc.state==original
 w.doc.redo();assert w.doc.state.drawings[0]==updated

def test_opacity_keyboard_and_no_selection(window,application):
 w=window;d=w.drawing;setup_selection(w);d.panel.show();application.processEvents()
 edit=d.opacity.lineEdit();QTest.mouseClick(edit,Qt.MouseButton.LeftButton,pos=QPoint(10,edit.height()//2));QTest.keyClicks(edit,'42');QTest.keyClick(edit,Qt.Key.Key_Return)
 assert w.doc.state.drawings[0].marks[0].opacity==.42
 d.selection.clear();before=w.doc.state;d.opacity.setValue(80);assert w.doc.state==before
