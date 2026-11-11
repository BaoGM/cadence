# SPDX-License-Identifier: GPL-3.0-only
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QCheckBox, QMessageBox

from test_sync1120 import application, link


@pytest.mark.parametrize('language', ['fr', 'en'])
def test_onion_control_tracks_global_setting_and_connection(application, link, monkeypatch, language):
    import ui_text
    from sync3d_dialog import SyncDialog
    monkeypatch.setattr(ui_text, '_language', language)
    link.window.drawing = SimpleNamespace(onion=QCheckBox(link.window))
    link.metadata = {'fps': 24}
    link.drawing_capability = True
    link.drawing_removal = True
    link.cameras = ['Camera']
    dialog = SyncDialog(link, link.window)
    dialog.show(); application.processEvents()
    assert dialog.send.isEnabled() and not dialog.onion.isEnabled()
    link.window.drawing.onion.setChecked(True)
    assert dialog.onion.isEnabled()
    dialog.onion.setChecked(True)
    link.window.drawing.onion.setChecked(False)
    assert not dialog.onion.isEnabled()
    link.metadata = None; dialog.refresh()
    link.window.drawing.onion.setChecked(True)
    assert not dialog.onion.isEnabled() and not dialog.send.isEnabled()
    link.metadata = {'fps': 24}; dialog.refresh()
    assert dialog.onion.isEnabled() and dialog.onion.isChecked()
    assert dialog.adapt.geometry().y() == dialog.adapt_all.geometry().y()
    assert dialog.adapt.geometry().right() < dialog.adapt_all.geometry().left()
    expected = ('Média courant…', 'Tous les médias…', 'Supprimer les dessins…') if language == 'fr' else ('Current media…', 'All media…', 'Delete drawings…')
    assert tuple(button.text().replace('&', '') for button in (dialog.adapt, dialog.adapt_all, dialog.remove)) == expected
    dialog.close()


@pytest.mark.parametrize('language,title,message', [
    ('fr', 'Supprimer les dessins', 'Supprimer tous les dessins créés par Cadence ?'),
    ('en', 'Delete drawings', 'Delete all drawings created by Cadence?'),
])
def test_removal_confirmation_is_concise_and_defaults_to_no(link, monkeypatch, language, title, message):
    import ui_text
    monkeypatch.setattr(ui_text, '_language', language)
    link.metadata = {'fps': 24}; link.drawing_removal = True
    questions = []
    def confirm(*args):
        questions.append(args)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, 'question', confirm)
    link.remove_drawings()
    assert questions[0][1:3] == (title, message)
    assert questions[0][-1] == QMessageBox.StandardButton.No
    assert not link.drawing_request
