# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path

from PySide6.QtGui import QKeySequence

from preferences import ShortcutDialog, defaults, load_preferences, validate
from test_drawing import application, window


def test_legacy_and_new_defaults(application):
    base=defaults({})
    assert (base['keyboard_layout'],base['scrub_pixels'],base['tooltips'])==('QWERTY',25,False)
    assert base['update_previews'] and base['auto_update_check']
    old=validate(dict(format='cadence-shortcuts',version=1,scrub_pixels=4,tooltips=True,
                      update_previews=False,auto_update_check=False),{})
    assert (old['keyboard_layout'],old['scrub_pixels'],old['tooltips'])==('QWERTY',4,True)
    assert not old['update_previews'] and not old['auto_update_check']


def test_keyboard_layouts_round_trip(window):
    w=window
    dialog=ShortcutDialog(w.action_registry,w.preferences,w)
    dialog.shortcutsChanged.connect(w.apply_preferences)
    undo='Édition/Annuler'
    pointer='Outils/Curseur'
    guide='Aide/Guide rapide'
    dialog.set_key(guide,'Alt+W')
    dialog.keyboard_layout.setCurrentText('AZERTY')
    assert w.action_registry[pointer][0].shortcut()==QKeySequence('A')
    assert w.action_registry[undo][0].shortcut()==QKeySequence('Ctrl+W')
    assert w.action_registry[guide][0].shortcut()==QKeySequence('Alt+Z')
    assert w.action_registry['Lecture/Clé précédente'][0].shortcut()==QKeySequence(';')
    assert w.action_registry['Lecture/Clé suivante'][0].shortcut()==QKeySequence(':')
    dialog.set_key(guide,'F12')
    dialog.keyboard_layout.setCurrentText('QWERTY')
    assert w.action_registry[guide][0].shortcut()==QKeySequence('Alt+W')
    dialog.keyboard_layout.setCurrentText('AZERTY')
    saved=load_preferences(w.action_registry)
    assert saved['keyboard_layout']=='AZERTY' and saved['shortcuts'][guide]=='F12'
    assert saved['shortcut_profiles']['QWERTY'][guide]=='Alt+W'
    dialog.reject(); dialog.deleteLater()


def test_direct_language_switch_preserves_project(window):
    w=window
    w.doc.project_path=Path('Dessin.cadence')
    w.doc.select(2,8); w.refresh()
    w.playlist.item(0).setSelected(True)
    state=w.doc.state
    for lang,menu,tool,caption,tree in (('en','File','Move','EN / fr','Watched folders'),
                                       ('fr','Fichier','Translation','FR / en','Dossiers suivis')):
        w.studio.language_button.click()
        assert w.studio.language_button.text()==caption
        assert w.menuBar().actions()[0].text()==menu
        assert w.drawing.tool_actions['translate'].text()==tool
        assert w.drawing.tool_buttons['translate'].accessibleName()==tool
        assert w.playlists_panel.tree.topLevelItem(0).text(0)==tree
        assert w.drawing.size.locale().name()==('en_GB' if lang=='en' else 'fr_FR')
        assert w.windowTitle().endswith('Dessin') and w.doc.state==state
        assert w.playlist.item(0).isSelected()
        assert w.playlist.item(0).text().endswith('frames' if lang=='en' else 'images')
        assert load_preferences(w.action_registry)['language']==lang


def test_silent_volume_slider(application):
    from app import STYLE
    from studio_transport import VolumeBars
    color='#68e0cf'
    def slider_colors():
        image=volume.slider.grab().toImage()
        return {image.pixelColor(x,y).name() for x in range(image.width()) for y in range(image.height())}
    volume=VolumeBars(); volume.setStyleSheet(STYLE+volume.styleSheet()); volume.show()
    volume.setValue(64); volume.setMuted(True)
    assert volume.slider.property('muted') and volume.value()==64
    assert color not in slider_colors()
    volume.setValue(0); volume.setMuted(False)
    assert volume.slider.property('muted')
    assert color not in slider_colors()
    volume.setValue(50)
    assert not volume.slider.property('muted')
    assert color in slider_colors()
    volume.close()
