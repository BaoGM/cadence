# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from drawing import DrawingKey,Mark
from test_drawing import application,window

@pytest.mark.parametrize('track',['audio','video','drawing'])
@pytest.mark.parametrize('operation',['delete','cut','copy'])
def test_drawing_menu_uses_selection_from_any_track(window,track,operation):
    w=window;d=w.doc;t=w.timeline
    keys=tuple(DrawingKey(i,i+1,(Mark(points=((.5,.5,1),)),)) for i in (2,5,8,12,22))
    d.state=replace(d.state,drawings=keys,selection=(4,15));w.refresh();t.selection_track=track
    menu=t.drawing_track.context_menu(t.x_for(8)+1)
    if operation=='delete':action=next(a for a in menu.actions() if 'Supprimer' in a.text())
    else:action=next(a for a in menu.actions() if a.data()==operation)
    assert action.isEnabled();action.trigger();menu.deleteLater()
    if operation=='copy':assert d.state.drawings==keys and len(d.drawing_clipboard)==3
    else:
        assert [k.start for k in d.state.drawings]==[2,22]
        d.undo();assert d.state.drawings==keys
        d.redo();assert [k.start for k in d.state.drawings]==[2,22]
    assert t.height()==126

def test_right_click_outside_selection_targets_only_clicked_key(window):
    w=window;d=w.doc;t=w.timeline
    keys=tuple(DrawingKey(i,i+1,()) for i in (2,5,8,22))
    d.state=replace(d.state,drawings=keys,selection=(4,10));w.refresh();t.selection_track='audio'
    menu=t.drawing_track.context_menu(t.x_for(22)+1)
    next(a for a in menu.actions() if 'Supprimer' in a.text()).trigger();menu.deleteLater()
    assert [k.start for k in d.state.drawings]==[2,5,8]
