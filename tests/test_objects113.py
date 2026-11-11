# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from drawing import Mark,DrawingKey
from test_drawing import application,window

def test_lasso_clipboard_priority_and_history(window):
    w=window; w.request_frame=lambda:None; d=w.drawing
    marks=(Mark(points=((.2,.3,1),)),Mark(tool='text',text='Test',points=((.6,.5,1),)))
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(0,10,marks),)); w.refresh(); d.choose_tool('lasso')
    d.selection.indices=(0,); d.selection.source=w.doc.state.drawings; d.selection.key_start=0
    before=w.doc.state
    assert d.edit_objects('copy')
    w.delete_selection(); assert w.doc.state.drawings[0].marks==(marks[1],) and w.doc.state.segments==before.segments
    assert d.edit_objects('paste'); assert w.doc.state.drawings[0].marks==(marks[1],marks[0])
    assert d.edit_objects('cut'); assert w.doc.state.drawings[0].marks==(marks[1],)
    w.undo(); w.undo(); w.undo(); assert w.doc.state==before

import pytest

@pytest.mark.parametrize('operation',['delete','cut'])
@pytest.mark.parametrize('erase',[False,True])
def test_last_object_removes_key_and_undo_restores(window,operation,erase):
    w=window; w.request_frame=lambda:None; d=w.drawing
    mark=Mark(points=((.2,.3,1),))
    marks=(mark,)+( (Mark(tool='eraser',points=((.2,.3,1),)),) if erase else ())
    key=DrawingKey(0,1,marks); other=DrawingKey(5,6,(mark,))
    w.doc.state=replace(w.doc.state,drawings=(key,other)); w.refresh(); d.choose_tool('lasso')
    d.selection.indices=(0,); d.selection.source=w.doc.state.drawings; d.selection.key_start=0
    before=w.doc.state
    assert d.edit_objects(operation)
    assert w.doc.state.drawings==(other,) and w.doc.state.segments==before.segments
    w.undo(); assert w.doc.state==before
    w.redo(); assert w.doc.state.drawings==(other,)
    if operation=='cut':
        assert d.edit_objects('paste')
        assert w.doc.state.drawings[0].marks
