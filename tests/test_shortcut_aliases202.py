# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from preferences import validate
from test_drawing import application, window


def key(widget, shortcut):
    QTest.keySequence(widget,QKeySequence(shortcut))


def test_help_timeline_redo_and_text_input(window,application):
    w=window
    w.activateWindow(); w.viewer.setFocus(); application.processEvents()
    for shortcut in ('F1','?','Shift+?'):
        opened=[]
        def close_guide():
            dlg=application.activeModalWidget()
            if isinstance(dlg,QDialog):
                opened.append(dlg.windowTitle())
                dlg.reject()
        QTimer.singleShot(50,close_guide)
        if shortcut=='Shift+?': QTest.keyClick(w.viewer,Qt.Key_Question,Qt.ShiftModifier)
        else: key(w.viewer,shortcut)
        assert opened==['Guide rapide - Cadence']
        w.activateWindow(); w.viewer.setFocus(); application.processEvents()
    before=w.timeline.simple
    key(w.viewer,'Alt+Shift+T'); assert w.timeline.simple!=before
    key(w.viewer,'Alt+Shift+T'); assert w.timeline.simple==before
    w.drawing.add_marker(); w.undo()
    assert not w.doc.state.frame_markers and w.redo_action.isEnabled()
    key(w.viewer,'Ctrl+Shift+Z'); assert w.doc.state.frame_markers==(0,)
    field=QLineEdit(w); field.show(); field.setFocus()
    QTimer.singleShot(40,close_guide)
    QTest.keyClicks(field,'?'); assert field.text()=='?'
    w.drawing.choose_tool('text')
    center=QPointF(w.viewer.rect().center())
    w.drawing.begin(center,1); w.drawing.finish()
    editor=w.drawing.text_editor
    assert editor is QApplication.focusWidget()
    QTimer.singleShot(40,close_guide)
    QTest.keyClicks(editor,'?'); assert editor.toPlainText()=='?'
    QTest.keyClick(editor,Qt.Key_Return)
    assert w.doc.state.drawings[0].marks[-1].text=='?'


def test_aliases_yield_to_custom_bindings_and_existing_preferences(window,application):
    w=window
    forward='Lecture/Image suivante'; backward='Lecture/Image précédente'; guide='Aide/Guide rapide'
    timeline='Affichage/Basculer entre les vues de la timeline'
    supplied=dict(w.preferences['shortcuts'])
    supplied.update({forward:'?',backward:'Ctrl+Shift+Z'})
    w.apply_preferences(dict(w.preferences,shortcuts=supplied))
    assert len(w.action_registry[guide][0].shortcuts())==len(w.redo_action.shortcuts())==1
    w.activateWindow(); w.viewer.setFocus(); application.processEvents()
    key(w.viewer,'?'); assert w.doc.state.position==1
    key(w.viewer,'Ctrl+Shift+Z'); assert w.doc.state.position==0
    supplied.pop(timeline); supplied[guide]=''
    supplied.update({forward:'F1',backward:'Alt+Shift+T'})
    loaded=validate(dict(w.preferences,shortcut_defaults_revision=3,shortcuts=supplied),w.action_registry)
    assert loaded['shortcuts'][guide]==loaded['shortcuts'][timeline]==''
    w.apply_preferences(loaded)
    key(w.viewer,'F1'); assert w.doc.state.position==1
    key(w.viewer,'Alt+Shift+T'); assert w.doc.state.position==0
    supplied.update({guide:'Ctrl+F1','Édition/Rétablir':'Ctrl+F2'})
    w.apply_preferences(dict(w.preferences,shortcuts=supplied))
    assert w.action_registry[guide][0].shortcuts()==[QKeySequence('Ctrl+F1')]
    assert w.redo_action.shortcuts()==[QKeySequence('Ctrl+F2')]
