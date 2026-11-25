# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import pytest
from drawing import DrawingKey,Mark,active_key
from test_drawing import application,window
from PySide6.QtCore import QPointF
from PySide6.QtCore import QPoint,Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit


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


def test_newest_copy_routes_objects_frames_and_keys(scene,application):
    w=scene
    drawing=w.drawing
    doc=w.doc
    w.activateWindow()
    drawing.choose_tool('lasso')
    w.seek(3)
    drawing.selection.indices=(0,)
    drawing.selection.source=doc.state.drawings
    drawing.selection.key_start=2
    w.viewer.setFocus()
    application.processEvents()
    def key(target,sequence):
        QTest.keySequence(target,QKeySequence(sequence))
    original=doc.state
    key(w.viewer,'Ctrl+C')
    key(w.viewer,'Ctrl+V')
    assert doc.state.drawings[0].marks==original.drawings[0].marks*2
    assert doc.state.segments==original.segments
    key(w.viewer,'Ctrl+X')
    assert doc.state.drawings==original.drawings
    w.undo()
    assert len(doc.state.drawings[0].marks)==2
    w.redo()

    w.timeline.setFocus()
    w.timeline.selection_track='video'
    w.select(16,18)
    key(w.timeline,'Ctrl+C')
    assert w.clipboard_kind=='media' and not drawing.edit_objects('paste')
    assert not drawing.edit_clipboard('paste',20,20)
    w.select(20,24)
    key(w.timeline,'Ctrl+X')
    assert [(s.start,s.end) for s in doc.clipboard]==[(20,24)]
    w.seek(0)
    key(w.timeline,'Ctrl+V')
    assert (doc.state.segments[0].start,doc.state.segments[0].end)==(20,24)

    key_to_copy=doc.state.drawings[0]
    assert drawing.edit_clipboard('copy',key_to_copy.start,key_to_copy.end)
    assert w.clipboard_kind=='drawing' and not doc.track_clipboards and not doc.clipboard
    w.timeline.selection_track='video'
    doc.state=replace(doc.state,position=doc.state.length,selection=None)
    key(w.timeline,'Ctrl+C')
    key(w.timeline,'Ctrl+X')
    assert w.clipboard_kind=='drawing'
    w.seek(23)
    segments=doc.state.segments
    key(w.timeline,'Ctrl+V')
    assert active_key(doc.state.drawings,23).marks==key_to_copy.marks
    assert doc.state.segments==segments


def test_native_text_clipboard_replaces_frame_copy(scene,application):
    w=scene
    w.activateWindow()
    w.timeline.setFocus()
    application.processEvents()
    w.select(2,7)
    QTest.keySequence(w.timeline,QKeySequence('Ctrl+C'))
    assert w.clipboard_kind=='media' and w.doc.clipboard
    before=w.doc.state
    field=QLineEdit(w)
    field.show()
    field.setFocus()
    field.setText('nouvelle copie')
    field.selectAll()
    QTest.keySequence(field,QKeySequence('Ctrl+X'))
    assert not field.text() and application.clipboard().text()=='nouvelle copie'
    assert not w.doc.clipboard and not w.doc.track_clipboards
    QTest.keySequence(field,QKeySequence('Ctrl+V'))
    assert field.text()=='nouvelle copie'
    w.timeline.setFocus()
    QTest.keySequence(w.timeline,QKeySequence('Ctrl+V'))
    assert w.doc.state==before
    assert not w.drawing.edit_clipboard('paste',18,18)
    w.doc.saved_signature=w.doc.signature()
    w.close()
    assert application.clipboard().text()=='nouvelle copie'


@pytest.mark.parametrize('simple',[True,False])
def test_copy_cut_after_frame_and_key_navigation(scene,application,simple):
    w=scene; t=w.timeline
    w.workspaces.set_timeline_simple(simple)
    w.activateWindow(); t.setFocus(); application.processEvents()
    def keys(sequence):
        QTest.keySequence(application.focusWidget(),QKeySequence(sequence))
    def content():
        return [(seg.start,seg.end) for seg in w.doc.clipboard]
    w.seek(16)
    keys('Ctrl+C'); assert content()==[(16,17)]
    keys('Right'); keys('Ctrl+V'); assert w.doc.state.selection==(17,18)
    keys('Right'); keys('Ctrl+X'); assert content()==[(17,18)]
    keys('Right'); keys('Ctrl+V'); assert w.doc.state.selection==(19,20)

    key=w.doc.state.drawings[0]
    pos=QPoint(round(t.x_for((key.start+key.end)/2)),round(t.track_y('drawing')+2))
    QTest.mouseClick(t, Qt.LeftButton, pos=pos)
    keys('Right'); assert w.doc.state.position==key.start+1 and w.doc.state.drawings[0]==key
    keys('Ctrl+C'); assert w.doc.drawing_clipboard_length==4
    keys('.'); assert w.doc.state.position==8
    keys('Ctrl+V'); assert w.doc.state.selection==(8,12)
    keys('.'); assert w.doc.state.position==12
    keys('Ctrl+X'); assert w.doc.drawing_clipboard_length==3
    assert active_key(w.doc.state.drawings,8) and active_key(w.doc.state.drawings,12) is None
    for y in (1,t.ruler_y()+6,t.media_top()+7):
        menu=t.context_menu(QPoint(round(t.x_for(16.25)),y))
        assert next(a for a in menu.actions() if a.data()=='paste').isEnabled()
        menu.deleteLater()


def test_inline_annotation_uses_text_clipboard(scene,application):
    w=scene
    w.activateWindow()
    w.timeline.setFocus()
    application.processEvents()
    w.seek(20)
    QTest.keySequence(w.timeline,QKeySequence('Ctrl+C'))
    assert w.clipboard_kind=='media'
    before=w.doc.state
    w.drawing.choose_tool('text')
    w.drawing.begin(QPointF(w.viewer.rect().center()),1)
    w.drawing.finish()
    editor=w.drawing.text_editor
    assert editor is application.focusWidget()
    QTest.keyClicks(editor,'annotation')
    editor.selectAll()
    QTest.keySequence(editor,QKeySequence('Ctrl+C'))
    assert w.clipboard_kind is None and application.clipboard().text()=='annotation'
    QTest.keySequence(editor,QKeySequence('Ctrl+X'))
    assert not editor.toPlainText()
    QTest.keySequence(editor,QKeySequence('Ctrl+V'))
    assert editor.toPlainText()=='annotation'
    editor.finish(False)
    assert w.doc.state==before
