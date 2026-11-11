# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from drawing import DrawingKey,Mark,active_key
from test_drawing import application,window


@pytest.fixture
def scene(window,monkeypatch):
    w=window; monkeypatch.setattr(w,'request_frame',lambda:None)
    mark=Mark(points=((.2,.3,1.),),color='#12abcd')
    w.doc.state=replace(w.doc.state,drawings=(DrawingKey(2,6,(mark,)),DrawingKey(8,10,()),DrawingKey(12,15,(mark,))),position=20)
    w.refresh()
    return w


def context(w,frame):
    return w.timeline.drawing_track.context_menu(w.timeline.x_for(frame+.25))


def trigger(menu,operation):
    action=next(a for a in menu.actions() if a.data()==operation)
    assert action.isEnabled()
    action.trigger(); menu.deleteLater()


def test_context_copies_clicked_key_and_pastes_at_click_with_undo(scene):
    w=scene; original=w.doc.state
    trigger(context(w,4),'copy')
    assert w.doc.state==original and w.doc.drawing_clipboard[0].end==4
    trigger(context(w,23),'paste')
    pasted=active_key(w.doc.state.drawings,23)
    assert (pasted.start,pasted.end,pasted.marks)==(23,27,original.drawings[0].marks)
    assert w.doc.state.position==23 and w.doc.state.selection==(23,27)
    assert w.doc.state.segments==original.segments and w.doc.state.audio==original.audio
    w.undo(); assert w.doc.state==original
    w.redo(); assert active_key(w.doc.state.drawings,26)==pasted


def test_context_cut_selected_range_preserves_gaps_and_other_tracks(scene):
    w=scene; w.timeline.selection_track='drawing'
    w.doc.state=replace(w.doc.state,selection=(3,10)); w.refresh(); before=w.doc.state
    trigger(context(w,8),'cut')
    assert [(k.start,k.end) for k in w.doc.state.drawings]==[(2,3),(12,15)]
    assert [(k.start,k.end) for k in w.doc.drawing_clipboard]==[(0,3),(5,7)]
    assert w.doc.state.segments==before.segments and w.doc.state.audio==before.audio
    trigger(context(w,20),'paste')
    assert [(k.start,k.end) for k in w.doc.state.drawings][-2:]==[(20,23),(25,27)]
    assert not active_key(w.doc.state.drawings,24)
    w.undo(); w.undo(); assert w.doc.state==before


def test_right_click_outside_selection_targets_clicked_key(scene):
    w=scene; w.timeline.selection_track='drawing'
    w.doc.state=replace(w.doc.state,selection=(2,6)); w.refresh()
    trigger(context(w,13),'cut')
    assert [(k.start,k.end) for k in w.doc.state.drawings]==[(2,6),(8,10)]
    assert w.doc.drawing_clipboard_length==3


def test_empty_area_and_paste_beyond_end_are_disabled(scene):
    w=scene; menu=context(w,20)
    assert all(not a.isEnabled() for a in menu.actions() if a.data() in ('copy','cut','paste'))
    menu.deleteLater(); trigger(context(w,8),'copy')
    assert w.doc.drawing_clipboard==(DrawingKey(0,2,()),)
    menu=context(w,29); assert not next(a for a in menu.actions() if a.data()=='paste').isEnabled(); menu.deleteLater()
    before=w.doc.state
    assert not w.drawing.edit_clipboard('paste',29,29) and w.doc.state==before
    assert not w.doc.paste_drawings(-1)
    trigger(context(w,25),'paste'); assert active_key(w.doc.state.drawings,25).marks==()


def test_drawing_menu_clipboard_and_global_track_shortcuts(scene):
    w=scene; w.timeline.selection_track='video'; w.doc.state=replace(w.doc.state,position=4); w.refresh()
    w.drawing.clipboard_actions['copy'].trigger()
    assert w.doc.drawing_clipboard_length==4 and w.clipboard_kind=='drawing'
    w.drawing.clipboard_actions['cut'].trigger(); assert not active_key(w.doc.state.drawings,4)
    w.doc.state=replace(w.doc.state,position=20); w.drawing.clipboard_actions['paste'].trigger()
    assert active_key(w.doc.state.drawings,23).start==20
    w.doc.state=replace(w.doc.state,position=21,selection=None); w.copy_selection()
    assert w.doc.drawing_clipboard_length==4
    w.cut_selection(); assert not active_key(w.doc.state.drawings,20)
    w.doc.state=replace(w.doc.state,position=25); w.paste_selection()
    assert active_key(w.doc.state.drawings,28).start==25


def test_menu_groups_order_and_shortcut_migration(scene):
    from preferences import defaults,validate
    w=scene; groups={}
    for entry in w.menuBar().actions():
        menu=entry.menu()
        if menu: groups[menu.title()]=[a.property('sourceText') if not a.isSeparator() else None for a in menu.actions()]
    assert groups['Dessin']==['Afficher le calque de dessins',None,'Ajouter un marqueur','Dupliquer la clé au curseur',None,'Coller les clés','Copier les clés','Couper les clés',None,'Supprimer les clés','Supprimer les marqueurs']
    assert groups['Outils'][-3:]==['Recadrer le clip','Transformer la sélection ou le clip','Réinitialiser le cadrage du clip']
    data=defaults(w.action_registry); validate(data,w.action_registry)
    data['shortcuts']['Dessin/Copier la clé au curseur']='Ctrl+Alt+K'
    del data['shortcuts']['Dessin/Dupliquer la clé au curseur']
    assert validate(data,w.action_registry)['shortcuts']['Dessin/Dupliquer la clé au curseur']=='Ctrl+Alt+K'
