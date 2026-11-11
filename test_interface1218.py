# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMessageBox,QDialogButtonBox,QPushButton,QLabel,QStyle
from PySide6.QtTest import QTest
from drawing import DrawingKey,Mark
from preferences import ShortcutDialog,load_preferences
from test_drawing import application,window

def action(menu,data): return next(a for a in menu.actions() if a.data()==data)

def test_panel_menu_timeline_commands(window,application):
    w=window;t=w.timeline
    w.doc.state=replace(w.doc.state,position=5,selection=(3,12),drawings=(DrawingKey(4,9,(Mark(points=((.2,.2,1),)),)),))
    w.refresh();menu=w.createPopupMenu()
    assert action(menu,'timeline_simple').isCheckable()
    action(menu,'units_frames').trigger();assert t.units=='frames'
    action(menu,'add_marker').trigger();assert w.doc.state.frame_markers==(5,)
    menu.deleteLater();menu=w.createPopupMenu();assert not action(menu,'add_marker').isEnabled()
    action(menu,'delete_keys').trigger();assert not w.doc.state.drawings and w.doc.state.selection==(3,12)
    action(menu,'delete_markers').trigger();assert not w.doc.state.frame_markers
    action(menu,'timeline_simple').trigger();assert t.simple
    menu.deleteLater()

def test_all_tracks_units_and_equal_heights(window,application):
    w=window;t=w.timeline;w.doc.state=replace(w.doc.state,drawings=(DrawingKey(4,9,(Mark(),)),));w.refresh()
    rectangles=[t.track_rect(track) for track in ('video','audio','drawing')]
    assert len({r.height() for r in rectangles})==1
    assert rectangles[1].top()-rectangles[0].bottom()==rectangles[2].top()-rectangles[1].bottom()
    assert t.height()-rectangles[-1].bottom()<12
    for track in ('video','audio','drawing'):
        menu=t.drawing_track.context_menu(t.x_for(5)) if track=='drawing' else t.context_menu(QPoint(round(t.x_for(5)),t.track_y(track)+9))
        action(menu,'units_time').trigger();assert t.units=='time'
        action(menu,'units_frames').trigger();assert t.units=='frames'
        assert menu.actions()[2].isSeparator();menu.deleteLater()

def test_shortcut_categories_live_edit(window,application):
    w=window;d=ShortcutDialog(w.action_registry,w.preferences,w);d.shortcutsChanged.connect(w.apply_preferences);d.show()
    key='Dessin/Ajouter un marqueur';d.show_key(key);application.processEvents()
    assert set(d.key_tables)=={key.split('/',1)[0] for key in w.action_registry}
    assert d.key_tabs.currentWidget() is d.key_tables['Dessin']
    assert sum(table.rowCount() for table in d.key_tables.values())==len(w.action_registry)
    d.set_key(key,'Ctrl+Alt+F9');assert w.action_registry[key][0].shortcut()==QKeySequence('Ctrl+Alt+F9')
    assert load_preferences(w.action_registry)['shortcuts'][key]=='Ctrl+Alt+F9'
    d.set_key(key,'');assert w.action_registry[key][0].shortcut().isEmpty()
    d.reject();d.deleteLater()

def test_message_presentation_and_mnemonic(window,application,caplog):
    box=QMessageBox(QMessageBox.Icon.Warning,'Test','Un message de diagnostic sur plusieurs lignes.',QMessageBox.StandardButton.Ok|QMessageBox.StandardButton.Cancel,window)
    box.show();box.activateWindow();application.setActiveWindow(box);QTest.qWait(80)
    assert box.findChild(QDialogButtonBox).centerButtons()
    for button in box.findChildren(QPushButton):
        assert '&' in button.text() and button.style().styleHint(QStyle.StyleHint.SH_UnderlineShortcut)==1
    label=box.findChild(QLabel,'qt_msgbox_label');assert label.alignment()==Qt.AlignmentFlag.AlignCenter
    assert 'Un message de diagnostic' in caplog.text
    QTest.keyClick(box,Qt.Key.Key_O,Qt.KeyboardModifier.AltModifier);QTest.qWait(200)
    assert not box.isVisible();box.deleteLater()

def test_english_new_commands_and_categories(application,tmp_path,monkeypatch):
    from app import MainWindow
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'preferences.json'));monkeypatch.setenv('CADENCE_LANGUAGE','en')
    w=MainWindow()
    try:
        assert w.open_btn.text()=='Open media'
        assert w.action_registry['Fichier/Ouvrir des vidéos…'][0].text()=='Open media…'
        assert w.action_registry['Aide/Dossier des journaux'][0].text()=='Log folder'
        menu=w.createPopupMenu()
        for data,text in [('timeline_simple','Simplified timeline'),('units_time','Timecode'),('units_frames','Frames'),('add_marker','Add frame marker'),('delete_markers','Delete frame markers'),('delete_keys','Delete keyframes')]:
            assert action(menu,data).text()==text
        d=ShortcutDialog(w.action_registry,w.preferences,w);d.ensure_keys()
        assert [d.key_tabs.tabText(i) for i in range(d.key_tabs.count())]==['File','Edit','Playback','View','Compare','Drawing','Tools','Help']
        d.reject();d.deleteLater();menu.deleteLater()
    finally:w.close();application.processEvents()
