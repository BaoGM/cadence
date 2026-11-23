# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from pathlib import Path
import threading

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox, QCheckBox, QPushButton

from playlist_store import PlaylistStore, scan_folder
from test_drawing import application, window


def immediate_tasks(w):
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    original=w.playlists_panel.browse
    def browse(*args,**kwargs):
        with patch('playlist_ui.Thread',side_effect=lambda target,**kw:type('Inline',(),{'start':staticmethod(target)})()):
            original(*args,**kwargs)
        QApplication.processEvents()
    w.playlists_panel.browse=browse


def test_folder_arrows_and_double_click_navigation(window, tmp_path, monkeypatch):
    w = window; panel = w.playlists_panel; immediate_tasks(w)
    root = tmp_path/'root'; leaf = root/'leaf'; branch = root/'branch'; child = branch/'child'
    leaf.mkdir(parents=True); child.mkdir(parents=True)
    (leaf/'video.mp4').write_bytes(b'video')
    identity = panel.store.create('Root', root=root); panel.rebuild((identity, str(root)))
    item = panel.tree.currentItem()
    assert item.childCount() == 2 and not panel.open_button.isEnabled()
    entries = {item.child(i).text(0):item.child(i) for i in range(item.childCount())}
    assert entries['leaf'].childCount() == 0 and entries['branch'].childCount() == 1
    errors=[]; monkeypatch.setattr(w, 'error', errors.append)
    panel.open_current(); assert not errors
    panel.double_clicked(item); assert item.isExpanded()
    panel.double_clicked(item); assert not item.isExpanded()
    panel.tree.setCurrentItem(entries['leaf'])
    assert panel.open_button.isEnabled() and entries['leaf'].childCount() == 0
    opened=[]; monkeypatch.setattr(panel, 'open_current', lambda: opened.append(panel.current))
    panel.double_clicked(entries['leaf'])
    assert opened == [(identity, str(leaf))] and not entries['leaf'].isExpanded()


def test_double_click_during_folder_scan_is_applied_after_scan(window, tmp_path, monkeypatch):
    panel=window.playlists_panel; folder=tmp_path/'folder'; folder.mkdir()
    (folder/'clip.mp4').write_bytes(b'data')
    workers=[]
    monkeypatch.setattr('playlist_ui.Thread',lambda target,**kw:type('Deferred',(),{'start':staticmethod(lambda:workers.append(target))})())
    identity=panel.store.create('Folder',root=folder); panel.rebuild((identity,str(folder)))
    item=panel.tree.currentItem(); panel.double_clicked(item)
    opened=[]; monkeypatch.setattr(panel,'open_current',lambda:opened.append(panel.current))
    assert window.job is None and window.dialog is None
    workers[0]()
    assert opened==[(identity,str(folder))]


def test_nested_playlist_alias_survives_scan_and_reload(window, tmp_path, monkeypatch):
    panel=window.playlists_panel; immediate_tasks(window)
    root=tmp_path/'root'; child=root/'original'; child.mkdir(parents=True)
    identity=panel.store.create('Root',root=root); panel.rebuild((identity,str(root)))
    item=panel.tree.currentItem().child(0); panel.tree.setCurrentItem(item)
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:('Renamed',True))
    panel.rename(); assert item.text(0)=='Renamed' and child.is_dir()
    panel.store.scanned(identity,child,[])
    store=PlaylistStore(panel.store.path)
    assert store.folder_name(identity,child)=='Renamed' and store.entry(identity)['name']=='Root'
    panel.rebuild((identity,str(root)))
    assert panel.tree.currentItem().child(0).text(0)=='Renamed'


def test_temporary_can_be_renamed_removed_and_closed_without_question(window, monkeypatch):
    panel=window.playlists_panel; panel.archive_current()
    assert panel.temporary
    record=panel.temporary[0]; original=window.doc
    panel.rebuild(('temporary',record['id']))
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:('Keep for session',True))
    panel.rename(); assert record['name']=='Keep for session'
    panel.remove_temporary(); assert not panel.temporary and window.doc is original
    panel.archive_current()
    record=panel.temporary[0]; record['doc'].saved_signature=None
    monkeypatch.setattr(window,'confirm_discard',lambda:True)
    def forbidden(*a,**k): raise AssertionError('Temporary confirmation shown')
    monkeypatch.setattr(QMessageBox,'question',forbidden)
    assert window.close()


def test_only_edit_mode_is_shown_in_compact_hover_frame(window, application):
    w=window; hover=w.hover_transport
    w.set_panel('transport',False); application.processEvents()
    hover.update_hover(hover.zone().center())
    assert hover.overlay.isVisible() and hover.toggle.isVisible()
    assert hover.overlay.findChildren(QCheckBox)==[hover.toggle]
    assert not hover.overlay.findChildren(QPushButton)
    assert hover.overlay.width()<190 and hover.overlay.height()<50
    assert not w.play_btn.isVisible() and not w.volume.isVisible()
    QTest.mouseClick(hover.toggle,Qt.MouseButton.LeftButton)
    assert w.workspaces.mode=='read'
    w.workspaces.switch('edit'); application.processEvents()
    hover.update_hover(hover.zone().center()); assert hover.toggle.isChecked()
    assert w.transport_widget.isHidden()
    hover.update_hover(QPoint(-100,-100)); assert not hover.overlay.isVisible()


def test_detached_view_has_no_owner_but_closes_with_main_window(window):
    from video_mirror import toggle
    toggle(window,True); mirror=window.video_mirror
    assert mirror.parentWidget() is None and mirror.windowHandle().transientParent() is None
    mirror.set_on_top(True)
    assert mirror.windowHandle().transientParent() is None
    window.doc.saved_signature=window.doc.signature()
    window.close(); assert not mirror.isVisible()
