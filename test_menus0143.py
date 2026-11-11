# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import Qt,QPoint,QPointF,QTimer
from PySide6.QtGui import QContextMenuEvent,QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMenu
from test_drawing import application,window
from preferences import defaults,validate,save_preferences,load_preferences

def test_hidden_shortcut_and_reset_both_mirrors(window,application):
    w=window; w.request_frame=lambda:None; w.activateWindow(); w.viewer.setFocus(); application.processEvents()
    menus={a.text():a.menu() for a in w.menuBar().actions()}
    assert 'Toute la timeline' not in [a.text() for a in menus['Affichage'].actions()]
    assert w.action_registry['Affichage/Toute la timeline'][0] in w.actions()
    w.timeline.zoom=3; w.timeline.view_start=12
    QTest.keyClick(w.viewer,Qt.Key.Key_0,Qt.KeyboardModifier.ControlModifier)
    assert w.timeline.zoom==1 and w.timeline.view_start==0
    w.toggle_flip('flip_h'); w.toggle_flip('flip_v'); before=w.doc.state; count=len(w.doc.undo_stack)
    w.viewer.zoom=2; w.viewer.pan=QPointF(17,22); w.viewer.angle=45
    QTest.keyClick(w.viewer,Qt.Key.Key_0)
    assert w.viewer.zoom==1 and w.viewer.pan==QPointF() and w.viewer.angle==0
    assert not w.doc.state.flip_h and not w.doc.state.flip_v and not w.hflip_action.isChecked() and not w.vflip_action.isChecked()
    assert len(w.doc.undo_stack)==count+1
    w.undo(); assert w.doc.state==before and w.viewer.flip_h and w.viewer.flip_v
    w.redo(); assert not w.doc.state.flip_h and not w.doc.state.flip_v
    w.reset_canvas(); assert len(w.doc.undo_stack)==count+1
    # Reordering must retain the live QAction instances and their shortcuts.
    hidden={'Comparaison/Mode de comparaison suivant','Lecture/Basculer le pas clé / image','Affichage/Toute la timeline','Lecture/Marquer entrée','Lecture/Marquer sortie','Édition/Insérer un vide…'}
    shown=[action for menu in menus.values() for action in menu.actions() if not action.isSeparator()]
    assert len(shown)==len(set(shown))==len(w.action_registry)-len(hidden)
    assert set(shown)=={action for key,(action,_) in w.action_registry.items() if key not in hidden}

def test_renamed_library_preserves_custom_shortcut(window):
    registry=window.action_registry; data=defaults(registry)
    new='Affichage/Afficher la liste de lecture'; old='Affichage/Liste de lecture et médias'
    data['shortcuts'].pop(new); data['shortcuts'][old]='Ctrl+Alt+8'
    save_preferences(data); loaded=load_preferences(registry)
    assert loaded['shortcuts'][new]=='Ctrl+Alt+8'
    window.apply_preferences(loaded); assert window.library_action.shortcut()==QKeySequence('Ctrl+Alt+8')
    assert validate(loaded,registry)['shortcuts'][new]=='Ctrl+Alt+8'

def test_background_panel_menu_works_with_locked_and_floating_panels(window,application):
    w=window; w.request_frame=lambda:None; assert not w.layout_editable
    w.library.hide(); w.comparison_panel.hide()
    def choose(target,key,point=None):
        found=[]
        def trigger():
            menu=application.activePopupWidget()
            if not isinstance(menu,QMenu): found.append('no popup'); return
            try:
                found.append(menu.objectName())
                action=next((a for a in menu.actions() if a.data()==key),None)
                if action is None or not action.isEnabled(): found.append('unavailable')
                else: action.trigger()
            finally: menu.close()
        QTimer.singleShot(30,trigger)
        point=point or target.rect().center(); event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,target.mapToGlobal(point))
        QApplication.sendEvent(target,event); application.processEvents()
        assert found==['panelVisibilityMenu']
    choose(w.viewer,'library'); assert w.library.isVisible() and w.library_action.isChecked()
    choose(w.viewer,'library'); assert w.library.isHidden() and not w.library_action.isChecked()
    choose(w.transport_widget.widget(),'tools',QPoint(200,10)); assert w.edit_toolbar.isHidden() and not w.toolbar_action.isChecked()
    choose(w.viewer,'tools'); assert w.edit_toolbar.isVisible() and w.toolbar_action.isChecked()
    w.layout_action.trigger(); w.library.show(); w.library.setFloating(True); application.processEvents()
    # A detached panel's empty background offers the same menu.
    choose(w.library.widget(),'comparison',QPoint(2,2)); assert w.comparison_panel.isVisible() and w.panel_actions['comparison'].isChecked()
    w.layout_action.trigger(); application.processEvents(); assert not w.library.isFloating()
    w.header.hide(); w.toggle_fullscreen(); application.processEvents()
    choose(w.viewer,'header'); assert not w.video_fullscreen and not w.header.isHidden()
