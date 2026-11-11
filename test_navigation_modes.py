# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from test_drawing import application,window
from drawing import DrawingKey
from model import State,Segment
from comparison import MODES
from navigation_modes import toggle_step


def test_shortcut_only_actions_cycle_and_rebind(window,application):
    w=window; w.activateWindow(); w.viewer.setFocus(); QTest.qWait(40)
    key='Comparaison/Mode de comparaison suivant'
    action,default=w.action_registry[key]
    menu_actions=[a for entry in w.menuBar().actions() for a in entry.menu().actions()]
    assert action not in menu_actions
    assert w.action_registry['Lecture/Basculer le pas clé / image'][0] not in menu_actions
    w.compare_media={'id':'reference'}
    # Avoid decoding synthetic media while exercising the real keyboard actions.
    w.request_frame=lambda:None
    for _,mode in MODES:
        QTest.keySequence(w,QKeySequence(default)); application.processEvents()
        assert w.compare_enabled.isChecked() and w.compare_mode.currentData()==mode
    QTest.keySequence(w,QKeySequence(default)); assert not w.compare_enabled.isChecked()
    data={**w.preferences,'shortcuts':{**w.preferences['shortcuts'],key:'Ctrl+Alt+J'}}
    w.apply_preferences(data)
    QTest.keySequence(w,QKeySequence(default)); assert not w.compare_enabled.isChecked()
    QTest.keySequence(w,QKeySequence('Ctrl+Alt+J')); assert w.compare_enabled.isChecked()
    w.compare_media=None


def test_step_toggle_wrap_selection_buttons_and_persistence(window,application):
    w=window; w.doc.state=State((Segment(None,0,100),),position=10,selection=(4,80),
        drawings=(DrawingKey(10,11,()),DrawingKey(40,60,())),frame_markers=(70,))
    w.request_frame=lambda:None
    w.activateWindow(); w.viewer.setFocus(); QTest.qWait(40)
    assert w.next_key_btn.symbol=='last'
    for expected in (40,70,10):
        w.action_registry['Lecture/Clé suivante'][0].trigger(); assert w.doc.state.position==expected
    w.previous_key_btn.click(); assert w.doc.state.position==70
    QTest.keySequence(w,QKeySequence('K')); assert w.key_step
    assert w.next_key_btn.symbol=='last' and w.previous_key_btn.symbol=='first' and w.next_frame_btn.symbol=='next'
    w.action_registry['Lecture/Clé suivante'][0].trigger(); assert w.doc.state.position==71
    w.previous_key_btn.click(); assert w.doc.state.position==70
    QTest.keySequence(w,QKeySequence('Right')); assert w.doc.state.position==71
    assert w.doc.state.selection==(4,80)
    from playback_preferences import save,load
    save(w); toggle_step(w); assert not w.key_step
    load(w); assert w.key_step
    QTest.keySequence(w,QKeySequence('K')); assert not w.key_step
    w.next_frame_btn.click(); assert w.doc.state.position==72
    w.doc.state=replace(w.doc.state,position=99); w.step(1); assert w.doc.state.position==0
    w.step(-1); assert w.doc.state.position==99
    w.doc.state=replace(w.doc.state,drawings=(),frame_markers=())
    w.step_key(1); assert w.doc.state.position==99
    toggle_step(w); w.step_key(1); assert w.doc.state.position==0



def test_numeric_editing_does_not_change_navigation(window,application):
    w=window; w.compare_media={'id':'reference'}; w.request_frame=lambda:None
    w.exp_spin.setFocus(); application.processEvents()
    w.cycle_comparison(); toggle_step(w)
    assert not w.compare_enabled.isChecked() and not w.key_step
    w.compare_media=None
