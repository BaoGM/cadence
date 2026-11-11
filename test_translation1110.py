# SPDX-License-Identifier: GPL-3.0-only
import ast
import json
import re
from pathlib import Path

import pytest

import ui_text


@pytest.fixture(autouse=True)
def restore_language():
    previous=ui_text._language
    yield
    ui_text._language=previous


@pytest.mark.parametrize('original,expected',[
    ('Supprimer le marqueur','Delete frame marker'),
    ('Détacher','Float panel'),
    ('Audio prêt','Audio ready'),
    ('Marqueurs invalides.','Invalid frame markers.'),
    ('Raccourci invalide : Édition/Annuler','Invalid shortcut: Edit / Undo'),
    ('Décodage : Image 10 indisponible.','Decoding: Frame 10 unavailable.'),
    ('Référence B : Média source introuvable : Dessin','Reference B: Source media not found: Dessin'),
    ('Volume : 80 % · Muet\nGlisser : volume · Clic droit : Mute / Unmute','Volume: 80 % · Muted\nDrag: volume · Right-click: Mute / Unmute'),
    ('0/2 médias · Préparation de l’aperçu','0/2 media · Preparing preview'),
    ('Copie · 30 images · vidéo + audio','Copy · 30 frames · video + audio'),
    ('13 images · audio','13 frames · audio'),
    ('Insertion : image 42 · vide conservé','Insert at frame 42 · gap kept'),
    ('Copie : image 42','Copy at frame 42'),
    ('Conflit de raccourcis : Édition/Annuler et Outils/Curseur.','Shortcut conflict: Edit / Undo and Tools / Pointer.'),
    ('Réinitialiser « Édition/Annuler » ?','Reset “Edit / Undo”?'),
    ('Comparaison : Côte à côte\nClic : Dessus / dessous','Comparison: Side by side\nClick: Top / bottom'),
    ('IMAGE 120 / 240','FRAME 120 / 240'),
    ('1.5 Mo libérés.\n2 médias en cours conservés.\n0 dossiers occupés ou inaccessibles.','1.5 MB freed.\n2 active media kept.\n0 folders in use or inaccessible.'),
])
def test_english_dynamic_messages(original,expected):
    ui_text._language='en'
    assert ui_text.tr(original)==expected
    assert ui_text.tr(expected)==expected


@pytest.mark.parametrize('name',['Dessin','Annuler','Côte à côte','scrub Canvas Nouveau montage.mp4','Retour\nDessin'])
def test_filenames_are_preserved_in_translated_errors(name):
    ui_text._language='en'
    assert ui_text.tr(f'Média source introuvable : {name}')==f'Source media not found: {name}'
    assert ui_text.tr(f'Le média source a changé depuis l’import : {name}. Réimportez-le dans un nouveau projet.')==f'Source media has changed since import: {name}. Import it again into a new project.'
    assert ui_text.tr(f'Export terminé : {name}')==f'Export complete: {name}'


def test_catalog_has_unique_entries_and_valid_patterns():
    lines=(ui_text._root/'ui_en.txt').read_text(encoding='utf-8').splitlines()
    keys=[line.split(' => ',1)[0] for line in lines if ' => ' in line]
    assert len(keys)==len(set(keys))
    assert all(line.split(' => ',1)[1] for line in lines if ' => ' in line)
    for entry in json.loads((ui_text._root/'ui_patterns.json').read_text(encoding='utf-8')):
        if not isinstance(entry,dict): continue
        assert all(0<=index<len(entry['parts'])-1 for index in entry['translate'])


def test_french_ui_literals_have_english_translation():
    ui_text._language='en'
    missing=[]
    for path in Path(__file__).parent.glob('*.py'):
        if path.name.startswith(('test_','bench_')) or path.name in ('ui_text.py','smoke.py','guide.py'): continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id!='tr' or not node.args: continue
            value=node.args[0]
            if not isinstance(value,ast.Constant) or not isinstance(value.value,str): continue
            text=value.value
            if re.search('[éèàêîôçÉÀœ]',text) and text!='Français' and ui_text.tr(text)==text:
                missing.append((path.name,node.lineno,text))
    assert not missing


@pytest.mark.parametrize('lang',['fr','en'])
def test_runtime_ui_options_and_context_menus(tmp_path,monkeypatch,lang):
    monkeypatch.setenv('CADENCE_PREFS',str(tmp_path/'prefs.json'))
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    monkeypatch.setenv('CADENCE_LANGUAGE',lang)
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication,QLabel,QAbstractButton,QComboBox,QFileDialog
    import app
    from capture import StopHotkey
    from preferences import ShortcutDialog
    from shortcut_edit import ConflictDialog
    monkeypatch.setattr(StopHotkey,'register',lambda self:False)
    monkeypatch.setattr(app,'QSettings',lambda *args:QSettings(str(tmp_path/'settings.ini'),QSettings.Format.IniFormat))
    qt=QApplication.instance() or QApplication([])
    window=app.MainWindow()
    dialogs=[]
    try:
        options=ShortcutDialog(window.action_registry,window.preferences,window); options.ensure_keys(); dialogs.append(options)
        conflict=ConflictDialog(window,['Édition/Annuler','Outils/Curseur']); dialogs.append(conflict)
        popup=window.createPopupMenu(); dialogs.append(popup)
        browser=QFileDialog(window); dialogs.append(browser)
        assert options.tabs.tabText(1)==('Raccourcis' if lang=='fr' else 'Shortcuts')
        assert window.undo_action.text()==('Annuler' if lang=='fr' else 'Undo')
        for key,(action,_) in window.action_registry.items():
            expected=ui_text.tr(key).split(' / ',1)[-1]
            assert action.text()==expected,(key,action.text(),expected)
        if lang=='en':
            texts=[]
            for obj in window.findChildren(QLabel)+window.findChildren(QAbstractButton)+window.findChildren(QAction):
                texts.append(obj.text().replace('&',''))
                texts.append(obj.toolTip())
            for combo in window.findChildren(QComboBox):
                texts.extend(combo.itemText(i) for i in range(combo.count()))
            assert not [text for text in texts if re.search('[éèàêîôçÉÀœ]',text) and text!='Français']
            edit_table=options.key_tables['Édition']
            assert 'Undo' in [edit_table.item(i,0).text() for i in range(edit_table.rowCount())]
        else:
            labels=[label.text() for label in browser.findChildren(QLabel)]
            assert any('Nom' in label for label in labels),labels
    finally:
        for dialog in dialogs: dialog.deleteLater()
        window.doc.saved_signature=window.doc.signature(); window.close(); qt.processEvents()
