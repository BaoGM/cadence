# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import json
import pytest
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog,QMessageBox,QFileDialog,QLabel
from test_drawing import application,window
from preferences import ShortcutDialog,defaults,validate,save_preferences,load_preferences
import ui_text


@pytest.fixture(autouse=True)
def isolate(tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    monkeypatch.setenv('CADENCE_LANGUAGE','fr')
    yield
    ui_text._language='fr'


def test_options_tabs_persistence_and_legacy_shortcut(window,tmp_path,monkeypatch):
    w=window; dialog=ShortcutDialog(w.action_registry,w.preferences,w)
    assert [dialog.tabs.tabText(i) for i in range(3)]==['Préférences','Raccourcis','Vue et navigation']
    assert not dialog.clear_on_exit.isChecked() and dialog.language.currentData()=='fr'
    old=defaults(w.action_registry); old['shortcuts'].pop('Fichier/Options…')
    old['shortcuts']['Édition/Raccourcis et navigation…']='Ctrl+Alt+P'
    assert validate(old,w.action_registry)['shortcuts']['Fichier/Options…']=='Ctrl+Alt+P'
    dialog.language.setCurrentIndex(dialog.language.findData('en')); dialog.clear_on_exit.setChecked(True)
    dialog.accept(); saved=load_preferences(w.action_registry)
    assert saved['language']=='en' and saved['clear_cache_on_exit']
    before=Path(__import__('preferences').preference_path()).read_bytes()
    d=ShortcutDialog(w.action_registry,saved,w); d.language.setCurrentIndex(0); d.reject()
    assert Path(__import__('preferences').preference_path()).read_bytes()==before
    # Exchanging shortcuts must not silently change general preferences.
    source=tmp_path/'keys.json'; source.write_text(json.dumps(defaults(w.action_registry)),encoding='utf-8')
    d=ShortcutDialog(w.action_registry,saved,w)
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(source),''))
    d.import_file(); assert d.language.currentData()=='en' and d.clear_on_exit.isChecked()
    monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:QMessageBox.StandardButton.Yes)
    d.reset_all(); assert d.language.currentData()=='en' and d.clear_on_exit.isChecked()
    d.reject()


def test_actual_keyboard_dispatch_for_every_default(window,application):
    class CatchShortcut(QObject):
        def __init__(self): super().__init__(); self.delivered=[]
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Shortcut:
                self.delivered.append((obj,event.isAmbiguous())); return True
            return False
    w=window; guard=CatchShortcut(); w.activateWindow(); w.raise_(); w.viewer.setFocus()
    QTest.qWait(30); application.processEvents()
    registry=w.action_registry
    validate(defaults(registry),registry) # Includes prefix conflicts, not only duplicates.
    for action,default in registry.values():
        action.setEnabled(True); action.setShortcut(QKeySequence(default)); action.installEventFilter(guard)
    for key,(action,default) in registry.items():
        if not default: continue
        guard.delivered.clear(); QTest.keySequence(w,QKeySequence(default)); application.processEvents()
        assert guard.delivered==[(action,False)],(key,default,guard.delivered)
    for action,_ in registry.values(): action.removeEventFilter(guard)


@pytest.mark.parametrize('lang',['fr','en'])
def test_localized_menus_ids_guide_and_names(application,tmp_path,monkeypatch,lang):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json')); monkeypatch.setenv('CADENCE_LANGUAGE',lang)
    from app import MainWindow
    from guide import guide_text
    w=MainWindow()
    try:
        keys=set(w.action_registry)
        assert 'Fichier/Options…' in keys and 'Édition/Raccourcis et navigation…' not in keys
        assert 'Affichage/Réinitialiser le canvas' in keys
        titles=[a.text() for a in w.menuBar().actions()]
        assert titles[0]==('Fichier' if lang=='fr' else 'File')
        action=w.action_registry['Affichage/Réinitialiser le canvas'][0]
        assert action.text()==('Réinitialiser la vue' if lang=='fr' else 'Reset view')
        assert w.undo_action.text()==('Annuler' if lang=='fr' else 'Undo')
        view=next(a.menu() for a in w.menuBar().actions() if a.text()==ui_text.tr('Affichage'))
        assert view.actions()[-1] is w.reset_layout_action
        assert w.drawing.panel_action in view.actions()
        popup=w.createPopupMenu()
        assert next(a for a in popup.actions() if a.data()=='timeline').text()=='Timeline'
        text=guide_text(w.action_registry)
        assert all(action.text() in text for action,key in w.action_registry.values() if key)
        assert '**' not in text and '\u2014' not in text and '\u2013' not in text and '## ' not in text
        assert ('Fichier > Options' if lang=='fr' else 'File > Options') in text
        # User file names are data, even when they contain interface words.
        w.doc.project_path=Path('scrub Canvas Nouveau montage.cadence'); w.refresh()
        assert w.windowTitle().endswith('scrub Canvas Nouveau montage')
        popup.deleteLater()
    finally:
        w.doc.saved_signature=w.doc.signature(); w.close(); application.processEvents()


def make_entry(root,name):
    p=root/name; p.mkdir(parents=True)
    for filename in ('media.json','preview.avi','audio.s16','waveform-v1.npy'): (p/filename).write_bytes(b'cache')
    return p


def test_cache_cleanup_protects_current_reference_and_foreign_files(window,tmp_path,monkeypatch):
    import cache_tools
    root=tmp_path/'cache'; root.mkdir(exist_ok=True)
    active=make_entry(root,'a'*24); reference=make_entry(root,'b'*24); unused=make_entry(root,'c'*24)
    foreign=make_entry(root,'d'*24); (foreign/'original.mp4').write_bytes(b'source')
    recordings=root/'captures'; recordings.mkdir(); (recordings/'screen.mp4').write_bytes(b'recording')
    w=window; w.doc.media['a']['proxy']=str(active/'preview.avi')
    w.reference_sources={'ref':{'proxy':str(reference/'preview.avi')}}
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:QMessageBox.StandardButton.Ok)
    d=ShortcutDialog(w.action_registry,w.preferences,w); d.clear_cache(); d.reject()
    assert active.exists() and reference.exists() and not unused.exists()
    assert (foreign/'original.mp4').read_bytes()==b'source'
    assert (recordings/'screen.mp4').read_bytes()==b'recording'
    assert cache_tools.cache_bytes()==40
    deleted,kept,failed,freed=cache_tools.clear_cache()
    assert (deleted,kept,failed,freed)==(2,0,0,40) and foreign.exists()


def test_cache_cleanup_handles_locked_preview(tmp_path,monkeypatch):
    from cache_tools import clear_cache
    root=tmp_path/'cache'; entry=make_entry(root,'a'*24)
    original=Path.unlink
    def locked(path,*args,**kwargs):
        if path==entry/'preview.avi': raise PermissionError('Locked')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',locked)
    assert clear_cache()==(0,0,1,0)
    assert len(list(entry.iterdir()))==4


def test_cleanup_on_exit_after_decoders_stop(application,tmp_path,monkeypatch):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json'))
    from app import MainWindow
    import cache_tools
    w=MainWindow(); called=[]; w.preferences['clear_cache_on_exit']=True
    def cleanup():
        assert not w.decoder.isRunning() and not w.reference_decoder.isRunning()
        assert not w.transport.running and w.transport.pcm is None
        called.append(True)
    monkeypatch.setattr(cache_tools,'clear_cache',cleanup)
    w.close(); assert called==[True]
