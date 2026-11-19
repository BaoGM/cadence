# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPointF

from drawing import DrawingKey, Mark
from test_render1170 import application
from test_tracks1170 import two_tracks


def test_translate_key_without_selection_and_undo(application, tmp_path, monkeypatch):
    from app import MainWindow
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = MainWindow()
    doc, _, _ = two_tracks()
    marks = (Mark('brush', ((.1, .1, 1.), (.2, .2, 1.))),
             Mark('eraser', ((.15, .15, 1.),)),
             Mark('text', ((.4, .3, 1.),), text='Annotation'))
    keys = (DrawingKey(0, 10, marks), DrawingKey(20, 30, (marks[0],)))
    doc.state = replace(doc.state, drawings=keys, position=4)
    window.doc = doc
    window.viewer.set_frame(np.zeros((90, 160, 3), np.uint8))
    drawing = window.drawing
    try:
        assert window.action_registry['Outils/Translation de la clé'][0].shortcut().toString() == 'T'
        assert window.action_registry['Affichage/Timecode / frames'][0].shortcut().toString() == 'Alt+T'
        drawing.choose_tool('translate')
        assert not drawing.selection.indices
        drawing.selection.begin((.8, .8), 'translate')
        drawing.selection.move((.9, .7))
        drawing.finish()
        changed = doc.state.drawings
        assert changed[1] == keys[1]
        for before, after in zip(marks, changed[0].marks):
            assert before.tool == after.tool
            for a, b in zip(before.points, after.points):
                assert abs(b[0] - a[0] - .1) < 1e-8
                assert abs(b[1] - a[1] + .1) < 1e-8
        assert not drawing.selection.indices
        assert doc.undo() and doc.state.drawings == keys
        assert doc.redo() and doc.state.drawings == changed
        drawing.selection.begin((.5, .5), 'translate')
        drawing.selection.move((.7, .7)); drawing.cancel()
        assert doc.state.drawings == changed
        doc.state = replace(doc.state, position=15)
        drawing.selection.begin((.5, .5), 'translate'); drawing.finish()
        assert doc.state.drawings == changed
    finally:
        doc.saved_signature = doc.signature(); window.close(); application.processEvents()


def test_video_mirror_follows_frames_and_window_controls(application, tmp_path, monkeypatch):
    from app import MainWindow
    from PySide6.QtCore import Qt
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = MainWindow(); window.show()
    action = window.video_mirror_action
    try:
        action.trigger(); application.processEvents()
        mirror = window.video_mirror
        assert mirror.isVisible() and not mirror.isModal()
        for rgb in ((255, 0, 0), (0, 0, 255)):
            frame = np.zeros((90, 160, 3), np.uint8); frame[:] = rgb
            window.viewer.set_frame(frame); application.processEvents()
            image = mirror.canvas.grab().toImage()
            color = image.pixelColor(image.width() // 2, image.height() // 2)
            assert (color.red(), color.green(), color.blue()) == rgb
        mirror.on_top.setChecked(True)
        assert mirror.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        mirror.opacity.setValue(55)
        assert abs(mirror.windowOpacity() - .55) < .01
        mirror.close(); assert not action.isChecked() and not mirror.isVisible()
        action.trigger(); assert window.video_mirror is mirror and mirror.isVisible()
    finally:
        window.close(); application.processEvents()


def test_t_shortcut_migration_preserves_custom_binding(application, tmp_path, monkeypatch):
    from app import MainWindow
    from preferences import defaults, validate
    monkeypatch.setenv('CADENCE_PREFS', str(tmp_path / 'prefs.json'))
    window = MainWindow()
    try:
        data = defaults(window.action_registry)
        data['shortcut_defaults_revision'] = 2
        data['shortcuts'].pop('Outils/Translation de la clé')
        data['shortcuts']['Affichage/Timecode / frames'] = 'T'
        updated = validate(data, window.action_registry)['shortcuts']
        assert updated['Affichage/Timecode / frames'] == 'Alt+T'
        assert updated['Outils/Translation de la clé'] == 'T'
        data['shortcuts']['Affichage/Timecode / frames'] = 'Ctrl+Alt+T'
        data['shortcuts']['Outils/Pinceau'] = 'T'
        updated = validate(data, window.action_registry)['shortcuts']
        assert updated['Affichage/Timecode / frames'] == 'Ctrl+Alt+T'
        assert updated['Outils/Pinceau'] == 'T' and not updated['Outils/Translation de la clé']
    finally:
        window.close(); application.processEvents()
