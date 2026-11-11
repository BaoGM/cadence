# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from drawing import DrawingKey,Mark
from test_drawing import application,window

def setup_selection(w):
 d=w.drawing;d.choose_tool('lasso')
 marks=(Mark(points=((.2,.2,1.),(.4,.4,1.)),color='#ff0000'),Mark(tool='text',points=((.3,.3,1.),),text='Texte',color='#ff0000'),Mark(tool='group',children=(Mark(points=((.2,.2,1.),(.4,.4,1.)),color='#ff0000'),Mark(tool='eraser',points=((.3,.3,1.),))),color='#ff0000'),Mark(points=((.2,.2,1.),(.4,.4,1.)),color='#00ff00'))
 key=DrawingKey(2,15,marks);other=DrawingKey(20,21,(Mark(points=((.2,.2,1.),(.4,.4,1.)),color='#ff0000'),))
 w.doc.state=replace(w.doc.state,position=5,drawings=(key,other),selection=(5,7));w.refresh()
 d.selection.indices=(0,1,2);d.selection.source=w.doc.state.drawings;d.selection.key_start=2;d.selection.key=key
 return key,other

def test_color_gesture_full_key_one_undo(window):
 w=window;d=w.drawing;key,other=setup_selection(w);original=w.doc.state;n=len(w.doc.undo_stack)
 d.wheel.drag='hue';d.wheel.edited.emit('#0000ff');d.wheel.edited.emit('#ffffff')
 assert w.doc.state==original and d.selection.preview.marks[0].color=='#ffffff'
 d.wheel.drag=None;d.wheel.editFinished.emit()
 changed=w.doc.state.drawings[0]
 assert (changed.start,changed.end)==(2,15) and w.doc.state.drawings[1]==other
 assert [m.color for m in changed.marks]==['#ffffff']*3+['#00ff00']
 assert changed.marks[2].children[0].color=='#ffffff' and changed.marks[2].children[1]==key.marks[2].children[1]
 assert d.selection.indices==(0,1,2) and len(w.doc.undo_stack)==n+1
 w.doc.undo();assert w.doc.state==original
 w.doc.redo();assert w.doc.state.drawings[0]==changed

def test_hex_and_no_selection(window):
 w=window;d=w.drawing;setup_selection(w)
 d.hex.setText('#123456');d.read_color();assert w.doc.state.drawings[0].marks[0].color=='#123456'
 d.selection.clear();before=w.doc.state;d.wheel.edited.emit('#abcdef');assert w.doc.state==before

def test_color_abandons_stale_selection(window):
 w=window;d=w.drawing;setup_selection(w);d.wheel.drag='hue';d.wheel.edited.emit('#ffffff')
 w.doc.state=replace(w.doc.state,position=20);d.refresh();before=w.doc.state
 d.wheel.drag=None;d.wheel.editFinished.emit();assert w.doc.state==before
